"""Run the real MotionDetector against a bench RTSP stream and record its callbacks."""
from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field

from custom_components.rtsp_motion.detector import Callbacks, DetectorSettings, MotionDetector
from fakecam.scenarios import SCENARIOS
from runner.score import score

BASE = "rtsp://bench:benchpass@rtsp:8554"
JOIN_TIMEOUT = MotionDetector.OPEN_TIMEOUT + 5


def url_for(name: str, once: bool = True) -> str:
    return f"{BASE}/{'synthetic-once' if once else 'synthetic'}/{name}"


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
    def __init__(self) -> None:
        self.t0: float | None = None
        self.started = time.monotonic()
        self.events: list[tuple[float, str, float | None]] = []
        self.pre: list[tuple[str, float | None]] = []
        self._lock = threading.Lock()

    def _add(self, kind: str, value: float | None) -> None:
        now = time.monotonic()
        with self._lock:
            if self.t0 is None:
                self.pre.append((kind, value))  # shouldn't happen: keep, counted separately
                return
            self.events.append((now - self.t0, kind, value))

    def on_connected(self) -> None:
        with self._lock:
            if self.t0 is None:
                self.t0 = time.monotonic()
        self._add("connected", None)

    def on_disconnected(self, reason: str) -> None:
        self._add("lost", None)

    def on_motion_start(self, percent: float) -> None:
        self._add("start", percent)

    def on_motion_end(self, peak_percent: float) -> None:
        self._add("end", peak_percent)


def run_stream(url: str, settings: DetectorSettings, seconds: float) -> Recording:
    rec = _Recorder()
    det = MotionDetector(url, settings, rec)
    det.start()
    try:
        time.sleep(seconds)
    finally:
        det.stop()
        det.join(JOIN_TIMEOUT)
    with rec._lock:
        offset = (rec.t0 - rec.started) if rec.t0 is not None else None
        return Recording(list(rec.events), offset, list(rec.pre))


def run_scenario(name: str) -> dict:
    sc = SCENARIOS[name]
    settings = DetectorSettings()
    rec = run_stream(url_for(name), settings, sc.duration + 10)
    connected = rec.count("connected")
    motions = rec.motions(rec.connect_offset or 0.0)
    s = score(sc.truth, motions, settings.hold_seconds)
    lost = rec.count("lost")
    delay = statistics.median(s.delays) if s.delays else None
    ok = (connected >= 1 and s.misses == 0 and s.false_alarms <= sc.expect.max_false_alarms
          and s.stuck == 0 and lost == sc.expect.video_lost)
    return {"scenario": name, "truth": len(sc.truth), "hits": s.hits, "misses": s.misses,
            "false_alarms": s.false_alarms, "stuck": s.stuck, "lost": lost,
            "median_delay": delay, "passed": ok, "connected": connected,
            "connect_offset": rec.connect_offset, "delays": s.delays, "motions": motions,
            "events": rec.events, "pre_connect": rec.pre_connect}
