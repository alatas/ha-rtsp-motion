"""Publish a synthetic scenario, or a video file, to an RTSP server.

Faults are part of the stream: Pause (silence on an open session), Jump
(timestamp discontinuity) and Reopen (new session at another size).
"""
import argparse
import threading
import time
from fractions import Fraction

import av
import numpy as np

from fakecam.scenarios import SCENARIOS, Jump, Pause, Reopen

# The pts clock starts here, so a negative Jump (pts_back uses -3600 s) never
# goes below zero.
PTS_BASE_SECONDS = 7200


def _pick_codec() -> tuple[str, dict]:
    try:
        av.codec.Codec("libx264", "w")
        return "libx264", {"preset": "ultrafast", "tune": "zerolatency"}
    except Exception:
        return "mpeg4", {}


def _open_container(url: str):
    # Local paths (used by the tests) infer the format from the extension.
    if url.startswith("rtsp://"):
        return av.open(url, "w", format="rtsp", options={"rtsp_transport": "tcp"})
    return av.open(url, "w")


class _Output:
    """One publishing session: an output container with one encoded stream."""

    def __init__(self, url: str, width: int, height: int, fps: float):
        codec, opts = _pick_codec()
        self.fps = fps
        self.out = _open_container(url)
        self.stream = self.out.add_stream(codec, rate=Fraction(fps).limit_denominator(1000))
        self.stream.width, self.stream.height, self.stream.pix_fmt = width, height, "yuv420p"
        self.stream.options = {**opts, "g": str(max(1, round(fps)))}

    def send(self, img: np.ndarray, pts: int) -> None:
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        frame.pts = pts
        for packet in self.stream.encode(frame):
            self.out.mux(packet)

    def flush(self) -> None:
        for packet in self.stream.encode(None):
            self.out.mux(packet)

    def close(self) -> None:
        try:
            self.flush()
        finally:
            self.out.close()


def _close_kicked(old: "_Output") -> None:
    try:
        old.out.close()
    except Exception:  # the server already dropped this session
        pass


def _sleep_until(deadline: float, stop: threading.Event) -> bool:
    """Sleep to a monotonic deadline. True if stop was set meanwhile."""
    return stop.wait(max(0.0, deadline - time.monotonic()))


def _hold(out: _Output, img: np.ndarray, pts: int, deadline: float, stop) -> None:
    """Keep the stream alive after the content ends: the last frame, again and
    again, at the stream's fps with advancing timestamps."""
    while True:
        deadline += 1 / out.fps
        if _sleep_until(deadline, stop):
            return
        pts += 1
        out.send(img, pts)


def publish_scenario(s, url: str, loop: bool = True, stop: threading.Event | None = None) -> None:
    """Play a scenario. loop=False plays it once and then holds the last frame
    until stop is set (or the process is killed); the stream never ends."""
    stop = stop or threading.Event()
    base = round(PTS_BASE_SECONDS * s.fps)
    w, h = s.width, s.height
    out = _Output(url, w, h, s.fps)
    pts, deadline, last, dirty, reopened = base, time.monotonic(), None, False, False
    try:
        while True:
            for step in s.steps():
                if stop.is_set():
                    return
                if isinstance(step, Pause):
                    # silence, but the clock keeps running, as on a real stall
                    pts += round(step.seconds * s.fps)
                    deadline += step.seconds
                    if _sleep_until(deadline, stop):
                        return
                elif isinstance(step, Jump):
                    pts += round(step.seconds * s.fps)
                    dirty = True
                    if step.seconds < 0:
                        # ffmpeg's muxer refuses decreasing dts inside one
                        # session, so a backward jump is a session takeover
                        # with the clock set back (as after a camera reboot).
                        out.flush()
                        old, out = out, _Output(url, w, h, s.fps)
                        reopened = True
                elif isinstance(step, Reopen):
                    # mediamtx destroys an on-demand path (and kills this very
                    # process) when its publisher leaves, so the new session
                    # must take over before the old one is closed: the server
                    # kicks the old publisher and the readers see a clean
                    # session end.
                    out.flush()
                    w, h = step.width, step.height
                    old, out = out, _Output(url, w, h, s.fps)
                    reopened = True
                    dirty = True
                else:
                    if _sleep_until(deadline, stop):
                        return
                    deadline += 1 / s.fps
                    out.send(step, pts)
                    pts += 1
                    last = step
                    if reopened:  # the new session is publishing now
                        reopened = False
                        _close_kicked(old)
            if not loop:
                if last is not None:
                    _hold(out, last, pts, deadline, stop)
                return
            if dirty:  # size or clock were changed: start the next round clean
                out.flush()
                w, h = s.width, s.height
                old, out = out, _Output(url, w, h, s.fps)
                pts, dirty, reopened = base, False, True
    finally:
        out.close()


def publish_file(path: str, url: str, loop: bool = True, stop: threading.Event | None = None) -> None:
    """Remux a video file (no re-encoding), paced by packet time. loop=True
    repeats it with timestamps that keep increasing; loop=False ends after the
    last packet (use publish_file_hold to keep the stream alive instead)."""
    stop = stop or threading.Event()
    with av.open(path) as src:
        in_stream = src.streams.video[0]
        out = _open_container(url)
        out_stream = out.add_stream_from_template(in_stream)
        try:
            offset = 0.0  # seconds added to the file's own times, per round
            while True:
                start = time.monotonic()
                first = end = None  # first dts and end of the last picture, seconds
                for packet in src.demux(in_stream):
                    if packet.dts is None or packet.size == 0:
                        continue
                    tb = float(packet.time_base)
                    if first is None:
                        first = packet.dts * tb  # B-frames make this negative
                    t = packet.dts * tb - first
                    if _sleep_until(start + t, stop):
                        return
                    pts = packet.pts if packet.pts is not None else packet.dts
                    end = max(end or 0.0, (pts + (packet.duration or 0)) * tb)
                    shift = round(offset / tb)
                    packet.dts += shift
                    if packet.pts is not None:
                        packet.pts += shift
                    packet.stream = out_stream
                    out.mux(packet)
                if not loop:
                    return
                offset += end - first  # next round's first dts lands on this end
                src.seek(0)
        finally:
            out.close()


def publish_file_hold(path: str, url: str, stop: threading.Event | None = None) -> None:
    """Play a file once, then hold its last frame until stop/kill (the stream
    never ends). Re-encodes: a remux cannot repeat the last picture."""
    stop = stop or threading.Event()
    with av.open(path) as src:
        stream = src.streams.video[0]
        fps = float(stream.average_rate or 15)
        out = _Output(url, stream.width, stream.height, fps)
        pts, deadline, last = round(PTS_BASE_SECONDS * fps), time.monotonic(), None
        try:
            for frame in src.decode(stream):
                if _sleep_until(deadline, stop):
                    return
                deadline += 1 / fps
                last = frame.to_ndarray(format="rgb24")
                out.send(last, pts)
                pts += 1
            if last is not None:
                _hold(out, last, pts, deadline, stop)
        finally:
            out.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    what = p.add_mutually_exclusive_group(required=True)
    what.add_argument("--scenario", choices=sorted(SCENARIOS))
    what.add_argument("--file")
    p.add_argument("--url", required=True)
    p.add_argument("--once", action="store_true",
                   help="play once, then hold the last frame (the stream never ends)")
    args = p.parse_args(argv)

    if args.scenario:
        publish_scenario(SCENARIOS[args.scenario], args.url, loop=not args.once)
    elif args.once:
        publish_file_hold(args.file, args.url)
    else:
        publish_file(args.file, args.url, loop=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
