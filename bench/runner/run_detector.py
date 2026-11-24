"""Run the real MotionDetector against a bench RTSP stream and record its callbacks."""
from __future__ import annotations

import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field

from custom_components.rtsp_motion.detector import Callbacks, DetectorState, DetectorSettings, MotionDetector
from fakecam.scenarios import SCENARIOS
from runner.score import score

BASE = "rtsp://bench:benchpass@rtsp:8554"
JOIN_TIMEOUT = MotionDetector.OPEN_TIMEOUT + 5


def run_token() -> str:
    return uuid.uuid4().hex[:12]


def url_for(name: str, once: bool = True) -> str:
    """once=True: a unique path per call (synthetic-once/<name>/<token>), so the run
    always starts the scenario at t=0 instead of attaching to a lingering publisher."""
    if once:
        return f"{BASE}/synthetic-once/{name}/{run_token()}"
    return f"{BASE}/synthetic/{name}"


@dataclass
class Recording:
    """events: (seconds since first connect, kind, value). kind: connected|lost|start|end."""
    events: list[tuple[float, str, float | None]] = field(default_factory=list)
    # Seconds from run_stream() start to the first connect. A once-publisher starts
    # when the first reader asks, but the first frame only arrives after the open
    # (about 3 s: publisher start plus a catch-up burst of frames), so
    # scenario time = event time + connect_offset.
    # None = the stream never connected.
    connect_offset: float | None = 0.0
    # (kind, value) events that arrived before the first connect (should not happen).
    pre_connect: list[tuple[str, float | None]] = field(default_factory=list)
    # DetectorState.fps samples from on_update (about one per second, 0 when down).
    fps_samples: list[float] = field(default_factory=list)
    # Set when the run itself went wrong (not a detector finding).
    error: str | None = None

    def count(self, kind: str) -> int:
        n = sum(1 for e in self.events if e[1] == kind)
        return n + sum(1 for k, _v in self.pre_connect if k == kind)

    def motions(self, shift: float = 0.0) -> list[tuple[float, float | None]]:
        """(start, end|None) pairs; shift is added to every time."""
        out: list[tuple[float, float | None]] = []
        open_start: float | None = None
        for t, kind, _v in self.events:
            if kind == "start":
                if open_start is not None:
                    out.append((open_start + shift, None))
                open_start = t
            elif kind == "end" and open_start is not None:
                out.append((open_start + shift, t + shift))
                open_start = None
        if open_start is not None:
            out.append((open_start + shift, None))
        return out


class _Recorder(Callbacks):
    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self.t0: float | None = None
        self.started = clock()
        self.events: list[tuple[float, str, float | None]] = []
        self.fps: list[float] = []
        self.pre: list[tuple[str, float | None]] = []
        self._lock = threading.Lock()

    def _add(self, kind: str, value: float | None) -> None:
        now = self.clock()
        with self._lock:
            if self.t0 is None:
                self.pre.append((kind, value))  # shouldn't happen: keep, counted separately
                return
            self.events.append((now - self.t0, kind, value))

    def on_connected(self) -> None:
        with self._lock:
            if self.t0 is None:
                self.t0 = self.clock()
        self._add("connected", None)

    def on_disconnected(self, reason: str) -> None:
        self._add("lost", None)

    def on_motion_start(self, percent: float) -> None:
        self._add("start", percent)

    def on_motion_end(self, peak_percent: float) -> None:
        self._add("end", peak_percent)

    def on_update(self, state: DetectorState) -> None:
        if state.connected and state.fps > 0:
            with self._lock:
                self.fps.append(state.fps)


def run_stream(url: str, settings: DetectorSettings, seconds: float) -> Recording:
    rec = _Recorder()
    det = MotionDetector(url, settings, rec)
    det.start()
    try:
        time.sleep(seconds)
    finally:
        det.stop()
        det.join(JOIN_TIMEOUT)
    error = "detector thread did not stop" if det.is_alive() else None
    with rec._lock:
        offset = (rec.t0 - rec.started) if rec.t0 is not None else None
        return Recording(list(rec.events), offset, list(rec.pre), list(rec.fps), error)


class _FileDetector(MotionDetector):
    """Counts frames, so callbacks can be stamped with video time (frame / fps)."""

    def __init__(self, path: str, settings: DetectorSettings, callbacks: Callbacks, fps: float):
        super().__init__(path, settings, callbacks)
        self.fps = fps
        self.frames = 0

    def _frame_received(self) -> None:
        super()._frame_received()
        self.frames += 1

    @property
    def video_time(self) -> float:
        return max(0, self.frames - 1) / self.fps


def run_file(path: str, settings: DetectorSettings, fps: float) -> Recording:
    """Run the detector over a video file as fast as it decodes, in this thread.
    Event times are video seconds (frame count / fps), so the truth needs no shift."""
    det: _FileDetector | None = None
    rec = _Recorder(clock=lambda: det.video_time if det else 0.0)
    det = _FileDetector(path, settings, rec, fps)
    det._read_stream()
    det._end_motion()  # the file ended: close an open motion like a broken stream does
    with rec._lock:
        offset = 0.0 if rec.t0 is not None else None
        return Recording(list(rec.events), offset, list(rec.pre), [fps], None)


def score_recording(name: str, truth: list, rec: Recording, settings: DetectorSettings,
                    seconds: float) -> dict:
    """The row fields shared by synthetic and VIRAT runs (no pass/fail verdict)."""
    connected = rec.count("connected")
    motions = rec.motions(rec.connect_offset or 0.0)
    s = score(truth, motions, settings.hold_seconds)
    fps = statistics.median(rec.fps_samples) if rec.fps_samples else None
    delay = statistics.median(s.delays) if s.delays else None
    row = {"scenario": name, "truth": len(truth), "hits": s.hits, "covered": s.covered,
           "misses": s.misses,
            "false_alarms": s.false_alarms, "stuck": s.stuck, "lost": rec.count("lost"),
            "median_delay": delay, "fps": fps, "connected": connected,
            "connect_offset": rec.connect_offset, "delays": s.delays, "motions": motions,
            "events": rec.events, "pre_connect": rec.pre_connect, "run_seconds": seconds}
    if rec.error:
        row["error"] = rec.error
    return row


def run_scenario(name: str) -> dict:
    sc = SCENARIOS[name]
    settings = DetectorSettings()
    seconds = sc.duration + 10
    rec = run_stream(url_for(name), settings, seconds)
    row = score_recording(name, sc.truth, rec, settings, seconds)
    row["passed"] = (row["connected"] >= 1 and row["misses"] == 0
                     and row["false_alarms"] <= sc.expect.max_false_alarms
                     and row["stuck"] == 0 and row["lost"] == sc.expect.video_lost
                     and not row.get("error"))
    return row
