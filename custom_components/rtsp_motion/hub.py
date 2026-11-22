"""Connects one MotionDetector thread to Home Assistant."""
from __future__ import annotations

import io
import time
from datetime import datetime
from urllib.parse import quote

from PIL import Image

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_PERCENT,
    CONF_CONFIRM_FRAMES,
    CONF_HOLD_SECONDS,
    CONF_IGNORE_AREAS,
    CONF_MIN_PERCENT,
    CONF_PATH,
    CONF_PIXEL_THRESHOLD,
    DEFAULT_CONFIRM_FRAMES,
    DEFAULT_HOLD_SECONDS,
    DEFAULT_IGNORE_AREAS,
    DEFAULT_MIN_PERCENT,
    DEFAULT_PIXEL_THRESHOLD,
    DOMAIN,
    EVENT,
    MOTION_CLEARED,
    MOTION_DETECTED,
    MOTION_UPDATED,
    VIDEO_CONNECTED,
    VIDEO_LOST,
)
from .detector import Callbacks, DetectorSettings, DetectorState, MotionDetector

FPS_UPDATE_SECONDS = 10


def build_url(data: dict) -> str:
    auth = ""
    if data.get(CONF_USERNAME):
        auth = quote(data[CONF_USERNAME], safe="")
        if data.get(CONF_PASSWORD):
            auth += ":" + quote(data[CONF_PASSWORD], safe="")
        auth += "@"
    path = data.get(CONF_PATH, "").lstrip("/")
    return f"rtsp://{auth}{data[CONF_HOST]}:{data[CONF_PORT]}/{path}"


def parse_areas(text: str) -> list[tuple[float, float, float, float]]:
    """'65,0,35,12; 0,50,20,50' (percent) -> [(0.65, 0, 0.35, 0.12), ...]. Raises ValueError."""
    areas = []
    for part in (text or "").replace("\n", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        nums = [float(n) for n in part.split(",")]
        if len(nums) != 4 or any(n < 0 or n > 100 for n in nums):
            raise ValueError(part)
        areas.append(tuple(n / 100 for n in nums))
    return areas


def settings_from_options(options: dict) -> DetectorSettings:
    return DetectorSettings(
        min_percent=float(options.get(CONF_MIN_PERCENT, DEFAULT_MIN_PERCENT)),
        pixel_threshold=int(options.get(CONF_PIXEL_THRESHOLD, DEFAULT_PIXEL_THRESHOLD)),
        confirm_frames=int(options.get(CONF_CONFIRM_FRAMES, DEFAULT_CONFIRM_FRAMES)),
        hold_seconds=float(options.get(CONF_HOLD_SECONDS, DEFAULT_HOLD_SECONDS)),
        masks=parse_areas(options.get(CONF_IGNORE_AREAS, DEFAULT_IGNORE_AREAS)),
    )


def to_jpeg(rgb) -> bytes | None:
    if rgb is None:
        return None
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class RtspMotionHub(Callbacks):
    """Owns the detector thread; turns its callbacks into HA state, signals and events."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> None:
        self.hass = hass
        self.entry = entry
        self.device_id = device_id
        self.signal = f"{DOMAIN}_{entry.entry_id}"
        self.connected = False
        self.motion = False
        self.motion_percent: float | None = None   # peak change of the current/last motion
        self.last_motion: datetime | None = None
        self.fps = 0.0
        self._last_fps_push = 0.0
        self.detector = MotionDetector(
            build_url(entry.data), settings_from_options(entry.options), self
        )

    def start(self) -> None:
        self.detector.start()

    def stop(self) -> None:
        self.detector.stop()

    # ---- images (called in the executor) ----------------------------------

    def latest_jpeg(self) -> bytes | None:
        return to_jpeg(self.detector.latest_image())

    def alarm_jpeg(self) -> bytes | None:
        return to_jpeg(self.detector.alarm_image())

    # ---- detector callbacks (detector thread) -----------------------------

    def _to_loop(self, kind: str, percent: float | None = None) -> None:
        self.hass.loop.call_soon_threadsafe(self._handle, kind, percent)

    def on_connected(self) -> None:
        self._to_loop(VIDEO_CONNECTED)

    def on_disconnected(self, reason: str) -> None:
        self._to_loop(VIDEO_LOST)

    def on_motion_start(self, percent: float) -> None:
        self._to_loop(MOTION_DETECTED, percent)

    def on_motion_update(self, peak_percent: float) -> None:
        self._to_loop(MOTION_UPDATED, peak_percent)

    def on_motion_end(self, peak_percent: float) -> None:
        self._to_loop(MOTION_CLEARED, peak_percent)

    def on_update(self, state: DetectorState) -> None:
        now = time.monotonic()
        if now - self._last_fps_push >= FPS_UPDATE_SECONDS:
            self._last_fps_push = now
            self._to_loop("fps", state.fps)

    # ---- event loop ---------------------------------------------------------

    @callback
    def _handle(self, kind: str, percent: float | None) -> None:
        if kind == "fps":
            self.fps = percent or 0.0
            async_dispatcher_send(self.hass, self.signal)
            return
        if kind == VIDEO_CONNECTED:
            self.connected = True
        elif kind == VIDEO_LOST:
            self.connected = False
            self.fps = 0.0
        elif kind == MOTION_DETECTED:
            self.motion = True
            self.motion_percent = round(percent, 2)
            self.last_motion = dt_util.utcnow()
        elif kind == MOTION_UPDATED:
            self.motion_percent = round(percent, 2)
        elif kind == MOTION_CLEARED:
            self.motion = False
        async_dispatcher_send(self.hass, self.signal)
        data = {"device_id": self.device_id, "type": kind}
        if percent is not None:
            data[ATTR_PERCENT] = round(percent, 2)
        self.hass.bus.async_fire(EVENT, data)
