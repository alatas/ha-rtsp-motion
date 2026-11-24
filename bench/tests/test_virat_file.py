"""VIRAT file mode (no RTSP, faster than real time) and longest-first scheduling.

Uses generated clips in a temporary data dir: no VIRAT data, no RTSP server needed.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import av
import numpy as np

from runner.parallel import run_jobs

BENCH = Path(__file__).resolve().parents[1]


def _clip(data: Path, name: str, seconds: int, square: tuple[int, int] | None) -> None:
    """15 fps clip; a bright square is shown between square[0] and square[1] seconds."""
    (data / "videos").mkdir(parents=True, exist_ok=True)
    (data / "truth").mkdir(parents=True, exist_ok=True)
    out = av.open(str(data / "videos" / f"{name}.mp4"), "w")
    stream = out.add_stream("mpeg4", rate=15)
    stream.width, stream.height, stream.pix_fmt = 1280, 720, "yuv420p"
    for i in range(seconds * 15):
        img = np.full((720, 1280, 3), 50, np.uint8)
        if square and square[0] * 15 <= i < square[1] * 15:
            img[200:400, 300:600] = 220
        for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    out.close()
    truth = [list(square)] if square else []
    (data / "truth" / f"{name}.json").write_text(json.dumps({"fps": 15, "width": 1280, "truth": truth}))


def test_run_jobs_submits_in_the_given_order():
    started = []

    def job(name):
        def fn():
            started.append(name)
            return {"scenario": name, "passed": True}
        return fn

    jobs = [(n, job(n)) for n in ("a", "b", "c")]
    rows = run_jobs(jobs, 1, order=[2, 0, 1])
    assert started == ["c", "a", "b"]
    assert [r["scenario"] for r in rows] == ["a", "b", "c"]  # rows stay in job order


def test_file_mode_scores_a_clip_faster_than_real_time(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_VIRAT_DIR", str(tmp_path))
    _clip(tmp_path, "clip", 8, (3, 5))
    from runner import virat_run

    t0 = time.monotonic()
    row = virat_run.run_clip_file("clip")
    elapsed = time.monotonic() - t0

    assert row["connected"] == 1 and row["passed"]
    assert (row["hits"], row["misses"], row["false_alarms"], row["stuck"]) == (1, 0, 0, 0)
    assert 0 <= row["median_delay"] < 1.0  # stream time: no transport or connect lag
    assert row["run_seconds"] == 8.0
    assert elapsed < 8.0


def test_cli_file_mode_runs_longest_first_in_processes(tmp_path):
    data, res = tmp_path / "data", tmp_path / "res"
    _clip(data, "a_short", 3, None)
    _clip(data, "b_long", 9, (2, 4))
    r = subprocess.run([sys.executable, "-m", "runner", "virat", "--parallel", "1"],
                       cwd=BENCH, capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, BENCH_VIRAT_DIR=str(data), BENCH_RESULTS_DIR=str(res)))
    assert r.returncode == 0, r.stderr
    done = [line.split(":")[0] for line in r.stdout.splitlines() if line.endswith((": ok", ": ERROR"))]
    assert done == ["b_long", "a_short"]  # longest first
    rows = json.loads((res / "virat.json").read_text())["rows"]
    assert [row["scenario"] for row in rows] == ["a_short", "b_long"]  # report in name order
    assert rows[1]["hits"] == 1

    r = subprocess.run([sys.executable, "-m", "runner", "virat", "--parallel", "2"],
                       cwd=BENCH, capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, BENCH_VIRAT_DIR=str(data), BENCH_RESULTS_DIR=str(res)))
    assert r.returncode == 0, r.stderr
    assert json.loads((res / "virat.json").read_text())["totals"]["hits"] == 1
