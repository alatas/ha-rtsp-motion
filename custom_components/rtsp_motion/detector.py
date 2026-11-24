"""Pixel-change motion detector for one RTSP stream.

No Home Assistant imports here: the module only needs PyAV and numpy (both
ship with Home Assistant), so it can be tested on its own.

A background thread reads the stream, scales each frame down to a small
grayscale image and compares it with the frame from `compare_seconds` earlier.
A change bigger than `min_percent` of the watched area is confirmed
`confirm_frames` frames later (against the same earlier frame) to reject
one-frame decode glitches.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import av
import numpy as np

_LOGGER = logging.getLogger(__name__)

ANALYSIS_WIDTH = 640
# Default ignored area: the camera clock in the top-right corner (fractions of the frame).
DEFAULT_MASKS: list[tuple[float, float, float, float]] = [(0.65, 0.0, 0.35, 0.12)]


WARMUP_SECONDS = 0.5  # after connecting, on top of compare_seconds


class StreamClock:
    """Seconds of video seen, taken from the frames' own timestamps.

    A camera clock that jumps (backwards, or forwards by more than MAX_STEP) counts as
    one normal frame step instead, so the hold timer and the compare gap never see the
    jump. A real stall of a few seconds still counts as time.
    """

    MAX_STEP = 10.0

    def __init__(self) -> None:
        self._raw: float | None = None
        self._now = 0.0
        self._step = 1 / 15

    def advance(self, raw: float) -> float:
        if self._raw is not None:
            dt = raw - self._raw
            if 0 < dt <= self.MAX_STEP:
                if dt <= 1.0:
                    self._step = dt
            else:
                dt = self._step
            self._now += dt
        self._raw = raw
        return self._now


@dataclass
class DetectorSettings:
    min_percent: float = 0.5        # % of the watched area that must change
    pixel_threshold: int = 15       # brightness change (0-255) for a pixel to count
    confirm_frames: int = 3         # 0 = fire immediately
    hold_seconds: float = 5.0       # motion stays on this long after the last change
    compare_seconds: float = 0.5    # compare each frame with the one this much older
    masks: list[tuple[float, float, float, float]] = field(
        default_factory=lambda: list(DEFAULT_MASKS)
    )


@dataclass
class DetectorState:
    connected: bool = False
    motion: bool = False
    percent: float = 0.0            # change in the latest frame
    peak_percent: float = 0.0       # highest confirmed change during the current motion
    fps: float = 0.0
    last_motion: float | None = None  # stream time of the last confirmed change


class Callbacks:
    """Override the methods you need. Called from the detector thread."""

    def on_connected(self) -> None: ...
    def on_disconnected(self, reason: str) -> None: ...
    def on_motion_start(self, percent: float) -> None: ...
    def on_motion_update(self, peak_percent: float) -> None: ...
    def on_motion_end(self, peak_percent: float) -> None: ...
    def on_update(self, state: DetectorState) -> None: ...


class MotionDetector(threading.Thread):
    OPEN_TIMEOUT = 10.0
    READ_TIMEOUT = 4.0              # no packet for this long -> reconnect
    RETRY_DELAY = 3.0               # camera answers 404 for a few s after a reboot
    LOST_GRACE = 15.0               # short drops reconnect silently; longer = video lost
    UPDATE_INTERVAL = 1.0           # on_update rate limit

    def __init__(self, url: str, settings: DetectorSettings, callbacks: Callbacks) -> None:
        super().__init__(daemon=True, name="rtsp_motion")
        self.url = url
        self.settings = settings
        self.callbacks = callbacks
        self.state = DetectorState()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest_rgb: np.ndarray | None = None
        self._latest_changed: np.ndarray | None = None
        self._alarm_rgb: np.ndarray | None = None
        self._alarm_changed: np.ndarray | None = None
        self._keep: np.ndarray | None = None
        self._paused = False
        self._last_frame_at: float | None = None  # monotonic time of the newest frame
        self._dropped = False  # the stream broke and hasn't delivered a frame since

    # ---- public API -------------------------------------------------------

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        """Paused: video keeps flowing, but no motion is reported."""
        self._paused = value
        if value:
            self._end_motion()

    def update_settings(self, settings: DetectorSettings) -> None:
        self.settings = settings
        self._keep = None  # rebuild the mask on the next frame

    def latest_image(self, mark_changes: bool = True) -> np.ndarray | None:
        """Newest small RGB frame, changed pixels in red."""
        with self._lock:
            return _marked(self._latest_rgb, self._latest_changed if mark_changes else None)

    def alarm_image(self) -> np.ndarray | None:
        """Small RGB frame of the last confirmed change, changed pixels in red."""
        with self._lock:
            return _marked(self._alarm_rgb, self._alarm_changed)

    # ---- thread -----------------------------------------------------------

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._read_stream()
                reason = "stream ended"
            except Exception as err:  # noqa: BLE001 - any stream error means reconnect
                reason = redact(f"{type(err).__name__}: {err}")
            if self._stop_event.is_set():
                return
            if self.state.connected:
                # Without frames the hold timer can't run, so the motion ends here.
                self._end_motion()
                # Cameras often stall for a few seconds and come back. Reconnect quietly;
                # only report "video interrupted" once there has been no frame for
                # LOST_GRACE. Counted from the last frame, because a frozen camera that
                # keeps the connection open makes every reconnect attempt slow.
                if not self._dropped:
                    self._dropped = True
                    _LOGGER.debug("Stream dropped (%s); reconnecting", reason)
                down = time.monotonic() - (self._last_frame_at or time.monotonic())
                if down >= self.LOST_GRACE:
                    self.state.connected = False
                    self.state.fps = 0.0
                    _LOGGER.warning("Video interrupted: no video for %.0f s (%s)", down, reason)
                    self.callbacks.on_disconnected(reason)
            else:
                _LOGGER.debug("Connect failed (%s)", reason)
            self._stop_event.wait(self.RETRY_DELAY)

    def _read_stream(self) -> None:
        options = {"rtsp_transport": "tcp", "timeout": str(int(self.READ_TIMEOUT * 1e6))}
        with av.open(
            self.url, options=options, timeout=(self.OPEN_TIMEOUT, self.READ_TIMEOUT)
        ) as container:
            stream = container.streams.video[0]
            # Slice threading only: frame threading holds back one frame per thread
            # before the first picture comes out, which at low frame rates delays
            # detection by seconds.
            stream.thread_type = "SLICE"
            # A new connection restarts the stream timestamps, which the motion hold
            # timer uses, so a motion from before a quiet reconnect ends here.
            self._end_motion()
            clock = StreamClock()
            # The first pictures after connecting are often broken or half-decoded. Let
            # the reference move past them before comparing.
            warmup = self.settings.compare_seconds + WARMUP_SECONDS
            # Recent frames as (stream time, gray). history[0] is the reference: the
            # newest frame at least `compare_seconds` old. Comparing across that gap
            # (instead of with the previous frame) makes slow or distant movement show
            # up as a whole silhouette, not just thin edges.
            history: deque[tuple[float, np.ndarray]] = deque()
            pending_ref = None
            pending_since = 0.0
            pending_left = 0
            last_update = time.time()
            frames_since_update = 0
            for frame in container.decode(stream):
                if self._stop_event.is_set():
                    return
                now = time.time()
                # Stream timestamps keep the gap right even if decoding lags or bursts;
                # the clock smooths over camera clock jumps.
                t = clock.advance(frame.time if frame.time is not None else now)
                frames_since_update += 1

                height = round(frame.height * ANALYSIS_WIDTH / frame.width / 2) * 2
                small = frame.reformat(width=ANALYSIS_WIDTH, height=height, format="rgb24",
                                       interpolation="AREA").to_ndarray()
                gray = _gray(small)

                self._frame_received()
                if not self.state.connected:
                    self.state.connected = True
                    _LOGGER.info("Video connected (%dx%d)", frame.width, frame.height)
                    self.callbacks.on_connected()
                if self._keep is None or self._keep.shape != gray.shape:
                    self._keep = _build_keep(gray.shape, self.settings.masks)
                    history.clear()
                    pending_ref = None
                keep = self._keep
                watched = max(1, int(np.count_nonzero(keep)))
                s = self.settings

                changed = None
                fired_changed = None
                if history and t >= warmup:
                    ref = history[0][1]
                    changed = self._changed(ref, gray, keep)
                    self.state.percent = np.count_nonzero(changed) * 100.0 / watched
                    if pending_ref is not None:
                        pending_left -= 1
                        if pending_left <= 0:
                            confirm = self._changed(pending_ref, gray, keep)
                            pct = np.count_nonzero(confirm) * 100.0 / watched
                            if pct >= s.min_percent:
                                fired_changed = confirm
                                self._confirmed(pct, t)
                            else:
                                # A glitch: never let its frames become a reference.
                                while history and history[-1][0] >= pending_since:
                                    history.pop()
                            pending_ref = None
                    elif self.state.percent >= s.min_percent:
                        if s.confirm_frames <= 0:
                            fired_changed = changed
                            self._confirmed(self.state.percent, t)
                        else:
                            pending_ref = ref
                            pending_since = t
                            pending_left = s.confirm_frames
                history.append((t, gray))
                while len(history) > 1 and t - history[1][0] >= s.compare_seconds:
                    history.popleft()

                if (self.state.motion and self.state.last_motion is not None
                        and t - self.state.last_motion > s.hold_seconds):
                    self._end_motion()

                with self._lock:
                    self._latest_rgb = small
                    self._latest_changed = changed
                    if fired_changed is not None:
                        self._alarm_rgb = small
                        self._alarm_changed = fired_changed

                if now - last_update >= self.UPDATE_INTERVAL:
                    self.state.fps = frames_since_update / (now - last_update)
                    frames_since_update = 0
                    last_update = now
                    self.callbacks.on_update(self.state)

    def _frame_received(self) -> None:
        now = time.monotonic()
        if self._dropped:
            _LOGGER.debug("Reconnected after %.0f s without video",
                          now - (self._last_frame_at or now))
            self._dropped = False
        self._last_frame_at = now

    def _changed(self, a: np.ndarray, b: np.ndarray, keep: np.ndarray) -> np.ndarray:
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
        return (diff > self.settings.pixel_threshold) & keep

    def _confirmed(self, percent: float, now: float) -> None:
        if self._paused:
            return
        self.state.last_motion = now
        if self.state.motion:
            if percent > self.state.peak_percent:
                self.state.peak_percent = percent
                self.callbacks.on_motion_update(percent)
            return
        self.state.motion = True
        self.state.peak_percent = percent
        _LOGGER.info("Motion detected: %.2f%% of the picture changed", percent)
        self.callbacks.on_motion_start(percent)

    def _end_motion(self) -> None:
        if self.state.motion:
            self.state.motion = False
            self.callbacks.on_motion_end(self.state.peak_percent)


_CREDENTIALS = re.compile(r"(\w+://)[^/@\s'\"]+@")


def redact(text: str) -> str:
    """Hide user:password in any URL (FFmpeg error messages include the full URL)."""
    return _CREDENTIALS.sub(r"\1***@", text)


def _gray(rgb: np.ndarray) -> np.ndarray:
    """Luma (0-255). No extra blur: the AREA downscale already averages sensor noise.

    Every channel is widened to uint16 *before* multiplying; uint8 * 150 would wrap
    around and scramble the brightness, hiding all but very large changes.
    """
    c = rgb.astype(np.uint16)
    return ((c[..., 0] * 77 + c[..., 1] * 150 + c[..., 2] * 29) >> 8).astype(np.uint8)


def _build_keep(shape: tuple[int, int], masks) -> np.ndarray:
    h, w = shape
    keep = np.ones(shape, dtype=bool)
    for x, y, mw, mh in masks:
        keep[int(y * h):int((y + mh) * h), int(x * w):int((x + mw) * w)] = False
    return keep


def _marked(rgb: np.ndarray | None, changed: np.ndarray | None) -> np.ndarray | None:
    if rgb is None:
        return None
    if changed is None or not changed.any():
        return rgb.copy()
    out = rgb.copy()
    out[changed] = (255, 0, 0)
    return out
