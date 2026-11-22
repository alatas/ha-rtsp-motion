"""Detector tests on a generated video file (no camera, no Home Assistant)."""
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
    events, det = run(path, DetectorSettings(hold_seconds=0))
    starts = [p for kind, p in events if kind == "start"]
    # The square appearing and disappearing are both changes; the glitch and the clock are not.
    assert len(starts) == 2
    assert all(6.0 < p < 7.5 for p in starts)  # ~6.5% of the watched area
    assert det.alarm_image() is not None
    assert (det.alarm_image()[..., 0] == 255).any()  # red marks


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
