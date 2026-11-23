"""Publish a synthetic camera stream to an RTSP server."""
import argparse
import time

import av
import numpy as np

WIDTH, HEIGHT, FPS = 1280, 720, 15


def _pick_codec() -> tuple[str, dict]:
    try:
        av.codec.Codec("libx264", "w")
        return "libx264", {"preset": "ultrafast", "tune": "zerolatency"}
    except Exception:
        return "mpeg4", {}


def _static_frames():
    img = np.full((HEIGHT, WIDTH, 3), 128, dtype=np.uint8)
    while True:
        yield img


SCENARIOS = {"static": _static_frames}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    p.add_argument("--url", required=True)
    args = p.parse_args(argv)

    codec, opts = _pick_codec()
    out = av.open(args.url, "w", format="rtsp", options={"rtsp_transport": "tcp"})
    stream = out.add_stream(codec, rate=FPS)
    stream.width, stream.height, stream.pix_fmt = WIDTH, HEIGHT, "yuv420p"
    stream.options = {**opts, "g": str(FPS)}
    try:
        start = time.monotonic()
        for i, img in enumerate(SCENARIOS[args.scenario]()):
            delay = start + i / FPS - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            frame.pts = i
            for packet in stream.encode(frame):
                out.mux(packet)
    finally:
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
