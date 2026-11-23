import av
import pytest

from runner.probe import open_frames

URL = "rtsp://bench:{pw}@rtsp:8554/synthetic/static"


def test_static_stream_serves_frames():
    frames = open_frames(URL.format(pw="benchpass"), 30)
    assert len(frames) == 30
    assert all(f.width == 1280 and f.height == 720 for f in frames)


def test_wrong_password_is_refused():
    with pytest.raises(av.error.HTTPUnauthorizedError):
        open_frames(URL.format(pw="benchpass2"), 1)
