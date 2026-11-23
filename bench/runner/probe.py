"""Helpers to read frames from an RTSP URL."""
import av


def open_frames(url: str, n: int, timeout: float = 15) -> list[av.VideoFrame]:
    """Read n decoded video frames from url. Raises av errors (e.g.
    av.error.HTTPUnauthorizedError on a bad password)."""
    options = {"rtsp_transport": "tcp", "timeout": str(int(timeout * 1_000_000))}
    frames: list[av.VideoFrame] = []
    with av.open(url, options=options, timeout=timeout) as container:
        stream = container.streams.video[0]
        for packet in container.demux(stream):
            for frame in packet.decode():
                frames.append(frame)
                if len(frames) >= n:
                    return frames
    return frames
