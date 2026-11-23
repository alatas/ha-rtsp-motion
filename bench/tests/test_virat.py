import io
import json
import urllib.request

import av
import numpy as np
import pytest

from virat import fetch
from virat.truth import moving_intervals


def _line(oid, frame, x, y, w, h, typ, dur=300):
    return f"{oid} {dur} {frame} {x} {y} {w} {h} {typ}"


def test_static_boxes_are_not_motion():
    lines = [_line(1, f, 100, 200, 80, 40, 2) for f in range(300)]
    assert moving_intervals(lines, 30.0, 1280) == []


def test_walking_person_interval():
    lines = [_line(7, f, 10 * (f - 60), 300, 30, 80, 1, 180) for f in range(60, 241)]
    out = moving_intervals(lines, 30.0, 1280)
    assert len(out) == 1
    s, e = out[0]
    assert s == pytest.approx(2.0, abs=1.1)
    assert e == pytest.approx(8.0, abs=1.1)


def test_short_blip_dropped():
    # a box that moves fast but exists for only 0.3 s (9 frames at 30 fps)
    lines = [_line(3, f, 100 + 15 * (f - 100), 50, 60, 60, 1, 9) for f in range(100, 109)]
    assert moving_intervals(lines, 30.0, 1280) == []


def test_gap_merge_and_union():
    a = [_line(1, f, 10 * (f - 60), 0, 30, 80, 1) for f in range(60, 150)]
    b = [_line(2, f, 10 * (f - 140), 0, 30, 80, 1) for f in range(140, 230)]
    out = moving_intervals(a + b, 30.0, 1280, merge_gap=1.0)
    assert len(out) == 1
    assert moving_intervals(a + b, 30.0, 1280, merge_gap=0.1).__len__() == 2


def test_fetch_refuses_without_terms(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("network call made")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert fetch.main(["--dest", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == []
    out = capsys.readouterr()
    assert "viratdata.org" in out.out + out.err


def _tiny_mp4(path, fps=10, n=20, w=64, h=48):
    c = av.open(str(path), "w")
    s = c.add_stream("mpeg4", rate=fps)
    s.width, s.height, s.pix_fmt = w, h, "yuv420p"
    for i in range(n):
        img = np.full((h, w, 3), i * 5, np.uint8)
        for p in s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            c.mux(p)
    for p in s.encode():
        c.mux(p)
    c.close()


def test_fetch_downloads_and_writes_truth_with_fake_http(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src.mp4"
    _tiny_mp4(src)
    video_bytes = src.read_bytes()
    # synthetic annotations: walking person, 64 px wide video, 10 fps
    ann = "\n".join(_line(1, f, 3 * (f - 2), 5, 8, 8, 1, 20) for f in range(2, 20)) + "\n"
    ann_bytes = ann.encode()
    clip = "VIRAT_S_FAKE_00_000000_000001"
    listing = {
        fetch.VIDEOS_FOLDER: [{"_id": "v1", "name": clip + ".mp4", "size": len(video_bytes)}],
        fetch.ANN_FOLDER: [
            {"_id": "a1", "name": clip + ".viratdata.objects.txt", "size": len(ann_bytes)}
        ],
    }
    blobs = {"v1": video_bytes, "a1": ann_bytes}
    calls = []

    monkeypatch.setattr(fetch, "list_items", lambda fid: listing[fid])

    def fake_dl(item_id, dest):
        calls.append(item_id)
        with open(dest, "wb") as f:
            f.write(blobs[item_id])

    monkeypatch.setattr(fetch, "download_item", fake_dl)
    subset = tmp_path / "subset.txt"
    subset.write_text(clip + "\n")
    dest = tmp_path / "d"
    argv = ["--accept-virat-terms", "--subset", str(subset), "--dest", str(dest)]
    assert fetch.main(argv) == 0
    out = capsys.readouterr().out
    assert "viratdata.org" in out and "redistribut" in out
    assert (dest / "videos" / (clip + ".mp4")).read_bytes() == video_bytes
    t = json.loads((dest / "truth" / (clip + ".json")).read_text())
    assert t["fps"] == pytest.approx(10)
    assert t["width"] == 64
    assert isinstance(t["truth"], list)
    assert not list(dest.rglob("*.part"))
    # second run: sizes match, nothing downloaded again
    n = len(calls)
    assert fetch.main(argv) == 0
    assert len(calls) == n
