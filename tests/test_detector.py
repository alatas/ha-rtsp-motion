"""Detector tests on a generated video file (no camera, no Home Assistant)."""
import time

import av
import numpy as np

from custom_components.rtsp_motion.detector import Callbacks, DetectorSettings, MotionDetector


def make_video(path, frames):
    out = av.open(str(path), "w")
    stream = out.add_stream("mpeg4", rate=15)
    stream.width, stream.height, stream.pix_fmt = 1280, 720, "yuv420p"
    for img in frames:
        for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    out.close()


class Recorder(Callbacks):
    def __init__(self):
        self.events = []

    def on_connected(self):
        self.events.append(("connected", None))

    def on_disconnected(self, reason):
        self.events.append(("disconnected", None))

    def on_motion_start(self, percent):
        self.events.append(("start", round(percent, 1)))

    def on_motion_end(self, peak_percent):
        self.events.append(("end", round(peak_percent, 1)))


def run(path, settings):
    rec = Recorder()
    det = MotionDetector(str(path), settings, rec)
    det.RETRY_DELAY = 0
    det._read_stream()  # read the file once, in this thread
    det._end_motion()
    return rec.events, det


def scene(i):
    img = np.full((720, 1280, 3), 60, np.uint8)
    if i == 30:                       # one-frame glitch
        img[:, :] = 200
    if 60 <= i < 90:                  # white square: 200x300 of 1280x720
        img[200:400, 300:600] = 255
    if i % 15 == 0:                   # "clock" in the default ignored area
        img[0:80, 900:1280] = (i * 7) % 255
    return img


def test_detects_square_ignores_glitch_and_clock(tmp_path):
    path = tmp_path / "scene.mp4"
    make_video(path, [scene(i) for i in range(120)])
    events, det = run(path, DetectorSettings(hold_seconds=1))
    starts = [p for kind, p in events if kind == "start"]
    # The square appearing and disappearing are both changes; the glitch and the clock are not.
    assert len(starts) == 2
    assert all(6.0 < p < 7.5 for p in starts)  # ~6.5% of the watched area
    assert det.alarm_image() is not None
    assert (det.alarm_image()[..., 0] == 255).any()  # red marks


def test_gray_is_monotonic_luma():
    """Regression: uint8 overflow once scrambled the luma and hid normal motion."""
    from custom_components.rtsp_motion.detector import _gray

    levels = np.arange(256, dtype=np.uint8)
    rgb = np.stack([levels, levels, levels], axis=-1)[None, :, :]
    gray = _gray(rgb)[0].astype(int)
    assert np.all(np.diff(gray) >= 0)
    assert abs(gray[200] - 200) <= 1 and abs(gray[255] - 255) <= 1
    # A dim object moving on a dark night-vision background must still count.
    dark = np.full((1, 1, 3), 40, np.uint8)
    brighter = np.full((1, 1, 3), 70, np.uint8)
    assert int(_gray(brighter)[0, 0]) - int(_gray(dark)[0, 0]) > 25


def test_small_dim_motion_is_detected(tmp_path):
    """A person-sized, low-contrast change (like night vision) must fire."""
    frames = []
    for i in range(60):
        img = np.full((720, 1280, 3), 40, np.uint8)
        if i >= 30:
            img[300:420, 500:620] = 75   # ~1.6% of the picture, +35 brightness
        frames.append(img)
    path = tmp_path / "dim.mp4"
    make_video(path, frames)
    events, _ = run(path, DetectorSettings(hold_seconds=0))
    assert any(kind == "start" for kind, _ in events)


def _slow_walker(tmp_path):
    """A 200x200 object crossing slowly (3 px per frame at 15 fps), like a far-away person."""
    frames = []
    for i in range(90):
        img = np.full((720, 1280, 3), 40, np.uint8)
        x = 200 + 3 * i
        img[300:500, x:x + 200] = 100
        frames.append(img)
    path = tmp_path / "walker.mp4"
    make_video(path, frames)
    return path


def test_slow_movement_needs_the_time_gap(tmp_path):
    path = _slow_walker(tmp_path)
    # Frame-to-frame only sees thin edges: below the 0.5% limit.
    events, _ = run(path, DetectorSettings(hold_seconds=0, compare_seconds=0))
    assert not any(kind == "start" for kind, _ in events)
    # Against the frame from 0.5 s earlier the whole movement counts.
    events, _ = run(path, DetectorSettings(hold_seconds=0, compare_seconds=0.5))
    assert any(kind == "start" for kind, _ in events)


def test_redact_hides_credentials():
    from custom_components.rtsp_motion.detector import redact

    msg = ("ExitError: Immediate exit requested: 'rtsp://user:p%40ss@192.0.2.10:554/live0'; "
           "last error log: [h264] error")
    out = redact(msg)
    assert "user" not in out and "p%40ss" not in out
    assert "rtsp://***@192.0.2.10:554/live0" in out
    assert redact("rtsp://192.0.2.10/live0") == "rtsp://192.0.2.10/live0"


class _FlakyDetector(MotionDetector):
    """run() against a scripted sequence of stream sessions instead of a camera."""

    RETRY_DELAY = 0.02
    LOST_GRACE = 0.3

    def __init__(self, sessions, callbacks):
        super().__init__("rtsp://user:secret@192.0.2.10/live0", DetectorSettings(), callbacks)
        self.sessions = list(sessions)

    def _read_stream(self):
        if not self.sessions:
            self.stop()
            raise OSError("done")
        kind = self.sessions.pop(0)
        if kind in ("ok", "stall", "motion"):  # got video, then the stream broke
            self._frame_received()
            if not self.state.connected:
                self.state.connected = True
                self.callbacks.on_connected()
            if kind == "motion":
                self._confirmed(5.0, 0.0)
            if kind == "stall":
                time.sleep(0.25)  # no packets until the read timeout
            raise OSError("Immediate exit requested: 'rtsp://user:secret@192.0.2.10/live0'")
        time.sleep(0.2 if kind == "slowfail" else 0.12)  # a failed connect attempt
        raise OSError("Connection refused: rtsp://user:secret@192.0.2.10/live0")


def test_short_drop_reconnects_quietly():
    rec = Recorder()
    det = _FlakyDetector(["ok", "fail", "ok"], rec)
    det.run()
    assert [k for k, _ in rec.events] == ["connected"]  # no "disconnected" for a 0.1 s drop


def test_long_outage_reports_once_without_password():
    import logging

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    logger = logging.getLogger("custom_components.rtsp_motion.detector")
    handler, old_level = Capture(), logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        rec = Recorder()
        _FlakyDetector(["ok"] + ["fail"] * 6, rec).run()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    text = "\n".join(handler.lines)
    assert [k for k, _ in rec.events] == ["connected", "disconnected"]
    assert "Video interrupted" in text
    assert "secret" not in text  # not even in debug lines


def test_lost_is_measured_from_the_last_frame():
    """A frozen camera that keeps the connection open: each reconnect attempt is slow
    (it connects, then waits for a frame), so the grace must count from the last frame,
    not from the first failed attempt."""
    rec = Recorder()
    _FlakyDetector(["stall", "slowfail", "ok"], rec).run()
    assert [k for k, _ in rec.events] == ["connected", "disconnected", "connected"]


def test_motion_ends_when_the_stream_breaks():
    """Without frames the hold timer can't run, so a broken stream ends the motion."""
    rec = Recorder()
    _FlakyDetector(["motion"], rec).run()
    assert [k for k, _ in rec.events] == ["connected", "start", "end"]


def test_stream_clock_ignores_timestamp_jumps():
    from custom_components.rtsp_motion.detector import StreamClock

    clock = StreamClock()
    raw = [100.0, 100.1, 100.2, 3700.2, 3700.3, 50.0, 50.1]
    got = [round(clock.advance(t), 3) for t in raw]
    assert got == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    # A real stall (a few seconds without frames) still counts as time.
    clock = StreamClock()
    assert [clock.advance(t) for t in (0.0, 1.0, 4.0)] == [0.0, 1.0, 4.0]


def test_forward_timestamp_jump_keeps_one_motion(tmp_path):
    """A camera clock jump in the middle of a movement must not end and restart it."""
    path = tmp_path / "jump.mp4"
    out = av.open(str(path), "w")
    stream = out.add_stream("mpeg4", rate=15)
    stream.width, stream.height, stream.pix_fmt = 1280, 720, "yuv420p"
    for i in range(150):
        img = np.full((720, 1280, 3), 40, np.uint8)
        if 30 <= i < 120:
            x = 100 + 8 * (i - 30)
            img[300:500, x:x + 150] = 110
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        frame.pts = i if i < 75 else i + 15 * 3600  # +1 h jump mid-movement
        for packet in stream.encode(frame):
            out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    out.close()
    events, _ = run(path, DetectorSettings(hold_seconds=2))
    assert [k for k, _ in events].count("start") == 1


def test_joining_between_keyframes_is_quiet(tmp_path):
    """A live stream is joined at a random point: until the next keyframe the decoder
    produces half-decoded pictures. They must not count as motion."""
    full = tmp_path / "full.ts"
    out = av.open(str(full), "w")
    stream = out.add_stream("libx264", rate=15)
    stream.width, stream.height, stream.pix_fmt = 1280, 720, "yuv420p"
    stream.options = {"g": "60", "keyint_min": "60", "sc_threshold": "0", "bf": "0"}
    yy, xx = np.mgrid[0:720, 0:1280]
    for i in range(150):
        img = np.zeros((720, 1280, 3), np.uint8)
        img[..., 0] = ((xx // 16 + yy // 16) % 2) * 200  # textured, still
        img[..., 1] = (xx * 255 // 1280).astype(np.uint8)
        for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    out.close()
    # Cut the start: begin 20 frames into the first GOP (next keyframe at frame 60).
    cut = tmp_path / "cut.ts"
    src, dst = av.open(str(full)), av.open(str(cut), "w")
    s_in = src.streams.video[0]
    s_out = dst.add_stream_from_template(s_in)
    for n, packet in enumerate(src.demux(s_in)):
        if packet.dts is None or n < 20:
            continue
        packet.stream = s_out
        dst.mux(packet)
    src.close()
    dst.close()
    events, _ = run(cut, DetectorSettings(hold_seconds=0))
    assert not any(kind == "start" for kind, _ in events), events


def test_hold_counts_from_when_the_change_was_seen(tmp_path):
    """At low frame rates confirm_frames takes seconds; the hold timer must start at
    the change, not at the confirmation."""
    frames = []
    for i in range(24):  # 4 fps: change at frame 8 = 2.0 s, confirmed 3 frames later
        img = np.full((720, 1280, 3), 40, np.uint8)
        if i >= 8:
            img[200:500, 300:700] = 160
        frames.append(img)
    path = tmp_path / "slow.mp4"
    out = av.open(str(path), "w")
    stream = out.add_stream("mpeg4", rate=4)
    stream.width, stream.height, stream.pix_fmt = 1280, 720, "yuv420p"
    for img in frames:
        for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    out.close()
    rec = Recorder()
    det = MotionDetector(str(path), DetectorSettings(hold_seconds=60), rec)
    det._read_stream()
    assert det.state.motion
    assert abs(det.state.last_motion - 2.0) < 0.01, det.state.last_motion


def test_glitch_in_the_first_frame_is_ignored(tmp_path):
    """Cameras often send a broken first picture after connecting. It must not become
    the reference that every following frame is compared with."""
    frames = [np.full((720, 1280, 3), 200 if i == 0 else 60, np.uint8) for i in range(45)]
    path = tmp_path / "first.mp4"
    make_video(path, frames)
    events, _ = run(path, DetectorSettings(hold_seconds=0))
    assert not any(kind == "start" for kind, _ in events)


def test_without_confirm_frames_glitch_fires(tmp_path):
    path = tmp_path / "glitch.mp4"
    make_video(path, [scene(i) for i in range(45)])
    events, _ = run(path, DetectorSettings(hold_seconds=0, confirm_frames=0))
    assert any(kind == "start" for kind, _ in events)


def test_paused_reports_nothing(tmp_path):
    path = tmp_path / "scene.mp4"
    make_video(path, [scene(i) for i in range(120)])
    rec = Recorder()
    det = MotionDetector(str(path), DetectorSettings(hold_seconds=0), rec)
    det.paused = True
    det._read_stream()
    assert not any(kind == "start" for kind, _ in rec.events)
