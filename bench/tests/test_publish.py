import threading
import time
from pathlib import Path

import av
import numpy as np
import pytest

from fakecam.publish import publish_file, publish_file_hold, publish_scenario
from fakecam.scenarios import SCENARIOS, Scenario, Expect
from runner.probe import open_frames

BASE = "rtsp://bench:benchpass@rtsp:8554"


def read_for(url: str, seconds: float):
    """Read frames until the deadline or until the session ends.
    Returns (frames_info, ended) where frames_info is a list of
    (arrival, frame.time, width, height) and ended says the session ended
    before the deadline."""
    options = {"rtsp_transport": "tcp", "timeout": "15000000"}
    info = []
    start = time.monotonic()
    try:
        with av.open(url, options=options, timeout=15) as container:
            for packet in container.demux(container.streams.video[0]):
                for frame in packet.decode():
                    now = time.monotonic() - start
                    info.append((now, frame.time, frame.width, frame.height))
                if time.monotonic() - start >= seconds:
                    return info, False
    except (av.error.EOFError, av.error.OSError, av.error.ExitError):
        pass
    return info, time.monotonic() - start < seconds


def make_clip(path: Path, seconds: int = 1, fps: int = 10) -> int:
    """Write a small h264 mp4 with noisy frames; returns the frame count."""
    rng = np.random.default_rng(1)
    n = seconds * fps
    with av.open(str(path), "w") as out:
        stream = out.add_stream("libx264", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 64, 64, "yuv420p"
        stream.options = {"g": str(fps)}
        for i in range(n):
            img = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            frame.pts = i
            for p in stream.encode(frame):
                out.mux(p)
        for p in stream.encode(None):
            out.mux(p)
    return n


def read_packets(path: Path):
    with av.open(str(path)) as c:
        return [(p.dts, bytes(p)) for p in c.demux(c.streams.video[0]) if p.size]


def tiny_scenario(n: int = 10, fps: float = 5) -> Scenario:
    rng = np.random.default_rng(2)
    frames = [rng.integers(0, 255, (64, 64, 3), dtype=np.uint8) for _ in range(n)]
    return Scenario("tiny", fps, 64, 64, n / fps, [], Expect(), lambda: iter(frames))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_paths_serve_each_scenario(name):
    frames = open_frames(f"{BASE}/synthetic/{name}", 5)
    assert len(frames) == 5


def test_once_path_serves_frames():
    frames = open_frames(f"{BASE}/synthetic-once/quiet_night", 5)
    assert len(frames) == 5


def test_pause_stops_frames():
    info, _ = read_for(f"{BASE}/synthetic/freeze_short", 25)
    gaps = [b[0] - a[0] for a, b in zip(info, info[1:])]
    assert 2.5 <= max(gaps) <= 4.5


def test_jump_shifts_timestamps():
    info, _ = read_for(f"{BASE}/synthetic/pts_forward", 22)
    steps = [b[1] - a[1] for a, b in zip(info, info[1:])]
    assert max(steps) > 3000


def test_negative_jump_replaces_session_and_stream_continues():
    # ffmpeg's muxer refuses decreasing dts, so the publisher takes the
    # session over with the clock set back; readers see the session end.
    info, ended = read_for(f"{BASE}/synthetic/pts_back", 25)
    assert ended
    frames = open_frames(f"{BASE}/synthetic/pts_back", 5)
    assert len(frames) == 5


def test_reopen_changes_size():
    info, ended = read_for(f"{BASE}/synthetic/size_change", 25)
    assert ended, "session should end when the publisher reopens"
    assert info[0][2:] == (1280, 720)
    frames = open_frames(f"{BASE}/synthetic/size_change", 5)
    assert all((f.width, f.height) == (1920, 1080) for f in frames)


def test_file_path_serves_remuxed_clip():
    videos = Path("/data/virat/videos")
    videos.mkdir(parents=True, exist_ok=True)
    clip = videos / "_bench_test.mp4"
    make_clip(clip)
    try:
        frames = open_frames(f"{BASE}/virat/_bench_test", 5)
        assert len(frames) == 5
        assert all((f.width, f.height) == (64, 64) for f in frames)
    finally:
        clip.unlink(missing_ok=True)


def run_in_thread(fn, seconds: float, *args):
    stop = threading.Event()
    t = threading.Thread(target=fn, args=(*args, stop), daemon=True)
    t.start()
    try:
        time.sleep(seconds)
    finally:
        stop.set()
        t.join(10)
    assert not t.is_alive()


def test_publish_file_remuxes_without_reencoding_and_paces(tmp_path):
    src, dst = tmp_path / "in.mp4", tmp_path / "out.mkv"
    make_clip(src, seconds=2)
    start = time.monotonic()
    publish_file(str(src), str(dst), loop=False)
    elapsed = time.monotonic() - start
    assert 1.5 <= elapsed <= 4
    assert [d for _, d in read_packets(src)] == [d for _, d in read_packets(dst)]


def test_publish_file_loops_with_monotonic_timestamps(tmp_path):
    src, dst = tmp_path / "in.mp4", tmp_path / "out.mkv"
    n = make_clip(src, seconds=1)

    def run(stop):
        publish_file(str(src), str(dst), True, stop)

    run_in_thread(lambda stop: run(stop), 2.6)
    packets = read_packets(dst)
    assert len(packets) > n + 5
    with av.open(str(dst)) as c:
        pts = [p.pts for p in c.demux(c.streams.video[0]) if p.size]
    assert len(set(pts)) == len(pts), "timestamps repeat: the second round restarted at 0"
    assert max(pts) > 1500  # ms: more than one 1 s round


def test_scenario_once_holds_last_frame(tmp_path):
    dst = tmp_path / "out.mkv"
    s = tiny_scenario()
    run_in_thread(lambda stop: publish_scenario(s, str(dst), False, stop), 3.5)
    with av.open(str(dst)) as c:
        frames = [f.to_ndarray(format="gray") for f in c.decode(video=0)]
    assert len(frames) >= 14
    held = frames[-1].astype(int) - frames[-2].astype(int)
    assert np.abs(held).mean() < 3


def test_file_once_holds_last_frame(tmp_path):
    src, dst = tmp_path / "in.mp4", tmp_path / "out.mkv"
    n = make_clip(src, seconds=1)
    run_in_thread(lambda stop: publish_file_hold(str(src), str(dst), stop), 3.0)
    with av.open(str(dst)) as c:
        frames = [f.to_ndarray(format="gray") for f in c.decode(video=0)]
    assert len(frames) >= n + 8
    held = frames[-1].astype(int) - frames[-2].astype(int)
    assert np.abs(held).mean() < 3
