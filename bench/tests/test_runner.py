import os
import re
import subprocess
import json
import sys
from pathlib import Path

import pytest

from custom_components.rtsp_motion.detector import DetectorSettings
from fakecam.scenarios import SCENARIOS
from runner.run_detector import run_scenario, run_stream, url_for
from runner.score import score


def _run(name):
    sc = SCENARIOS[name]
    return sc, run_stream(url_for(name), DetectorSettings(), sc.duration + 10)


def test_night_walker_is_hit():
    sc, rec = _run("night_walker")
    s = score(sc.truth, rec.motions(rec.connect_offset), DetectorSettings().hold_seconds)
    assert s.hits == 1
    assert s.delays[0] < 2.0


def test_quiet_night_has_no_alarm():
    _sc, rec = _run("quiet_night")
    assert rec.count("connected") >= 1
    assert not [e for e in rec.events if e[1] == "start"]


def test_freeze_long_reports_lost_once():
    _sc, rec = _run("freeze_long")
    assert rec.count("connected") >= 1
    kinds = [e[1] for e in rec.events]
    assert rec.count("lost") == 1
    assert "connected" in kinds[kinds.index("lost"):]


def test_cli_writes_report(tmp_path):
    bench = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-m", "runner", "synthetic", "--only", "quiet_night"],
                       cwd=bench, capture_output=True, text=True,
                       env=dict(os.environ, BENCH_RESULTS_DIR=str(tmp_path)))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "quiet_night" in (tmp_path / "synthetic.md").read_text()
    row = json.loads((tmp_path / "synthetic.json").read_text())[0]
    assert row["connected"] >= 1 and row["connect_offset"] is not None
    assert row["passed"]


# ---- parallel helper -------------------------------------------------------

import threading
import time

from runner.parallel import run_jobs


def _fake(name, pause=0.0, fail=False, log=None):
    def job():
        if log is not None:
            log.append(("start", name))
        time.sleep(pause)
        if log is not None:
            log.append(("end", name))
        if fail:
            raise RuntimeError("boom " + name)
        return {"scenario": name, "passed": True}
    return name, job


def test_parallel_one_is_sequential():
    log = []
    jobs = [_fake(n, 0.05, log=log) for n in "abc"]
    rows = run_jobs(jobs, 1)
    assert [r["scenario"] for r in rows] == ["a", "b", "c"]
    assert log == [("start", "a"), ("end", "a"), ("start", "b"), ("end", "b"),
                   ("start", "c"), ("end", "c")]


def test_parallel_keeps_order_and_survives_exceptions():
    jobs = [_fake("slow", 0.3), _fake("bad", 0.0, fail=True), _fake("fast", 0.0)]
    seen = []
    rows = run_jobs(jobs, 3, on_row=lambda partial: seen.append(len(partial)))
    assert [r["scenario"] for r in rows] == ["slow", "bad", "fast"]
    assert rows[1]["passed"] is False and "boom bad" in rows[1]["error"]
    assert rows[0]["passed"] and rows[2]["passed"]
    assert seen and seen[-1] == 3  # on_row fired as results arrived


def test_parallel_limits_concurrency():
    active, peak, lock = 0, 0, threading.Lock()

    def job():
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.1)
        with lock:
            active -= 1
        return {"scenario": "x", "passed": True}

    run_jobs([(str(i), job) for i in range(6)], 2)
    assert peak == 2


def test_parallel_runs_overlap():
    names = ["quiet_night", "clock_corner"]
    single = max(SCENARIOS[n].duration for n in names) + 10
    t = time.monotonic()
    rows = run_jobs([(n, lambda n=n: run_scenario(n)) for n in names], 2)
    wall = time.monotonic() - t
    assert [r["scenario"] for r in rows] == names
    assert wall < 1.5 * single
    assert all(r["connected"] >= 1 for r in rows)


def test_report_flags_timing_skew(tmp_path):
    from runner.report import write_report
    base = {"truth": 0, "hits": 0, "misses": 0, "false_alarms": 0, "stuck": 0, "lost": 0,
            "median_delay": None, "fps": 15.0, "passed": True}
    rows = [dict(base, scenario="a", connect_offset=3.0),
            dict(base, scenario="b", connect_offset=3.2),
            dict(base, scenario="c", connect_offset=3.1),
            dict(base, scenario="late", connect_offset=4.5, passed=False)]
    write_report(rows, str(tmp_path / "r.md"), str(tmp_path / "r.json"))
    lines = (tmp_path / "r.md").read_text().splitlines()
    assert "connect offset" in lines[0]
    by = {ln.split("|")[1].strip(): ln for ln in lines[2:]}
    assert "4.50s" in by["late"] and "timing skew" in by["late"]
    assert "timing skew" not in by["a"] and "timing skew" not in by["c"]


def test_parallel_on_done_gets_each_finished_row():
    done = []
    run_jobs([_fake("x", 0.2), _fake("y", 0.0)], 2, on_done=lambda r: done.append(r["scenario"]))
    assert done == ["y", "x"]


def test_parallel_keyboard_interrupt_returns_partial_rows():
    release = threading.Event()

    def slow(name):
        def job():
            release.wait(10)
            return {"scenario": name, "passed": True}
        return name, job

    def on_done(row):
        if row["scenario"] == "fast":
            raise KeyboardInterrupt  # simulates Ctrl-C arriving in the main thread

    jobs = [_fake("fast", 0.0), slow("slow1"), slow("slow2"), slow("slow3")]
    t = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt) as ei:
            run_jobs(jobs, 2, on_done=on_done)
        assert time.monotonic() - t < 3  # did not wait for the running and queued slow jobs
        assert ei.value.rows == [{"scenario": "fast", "passed": True}]
    finally:
        release.set()
        deadline = time.monotonic() + 5  # let the pool threads finish before teardown checks
        while time.monotonic() < deadline and any(
                th.name.startswith("ThreadPoolExecutor") for th in threading.enumerate()):
            time.sleep(0.05)


def test_cli_exits_130_on_interrupt_and_writes_partial_report(tmp_path, monkeypatch):
    from runner import __main__ as cli
    monkeypatch.setenv("BENCH_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "run_scenario", lambda n: {"scenario": n, "passed": True})

    def boom(jobs, parallel, on_row=None, on_done=None):
        err = KeyboardInterrupt()
        err.rows = [{"scenario": "a", "passed": True, "truth": 0, "hits": 0, "misses": 0,
                     "false_alarms": 0, "stuck": 0, "lost": 0, "median_delay": None,
                     "fps": 15.0, "connect_offset": 3.0}]
        raise err

    monkeypatch.setattr(cli, "run_jobs", boom)
    monkeypatch.setattr(sys, "argv", ["runner", "synthetic", "--parallel", "2"])
    assert cli.main() == 130
    assert "| a" in (tmp_path / "synthetic.md").read_text()


def test_url_for_once_is_unique_per_run():
    a, b = url_for("night_walker"), url_for("night_walker")
    assert a != b
    for u in (a, b):
        assert re.fullmatch(r"rtsp://bench:benchpass@rtsp:8554/synthetic-once/night_walker/[0-9a-f]{12}", u)
    assert url_for("night_walker", once=False).endswith("/synthetic/night_walker")


def test_mediamtx_once_paths_take_scenario_and_token():
    cfg = (Path(__file__).resolve().parents[1] / "mediamtx.yml").read_text()
    assert '"~^synthetic-once/([^/]+)/.+$"' in cfg
    assert '"~^virat-once/([^/]+)/.+$"' in cfg


def test_unknown_names_are_rejected_by_the_cli(tmp_path):
    env = dict(os.environ, BENCH_VIRAT_DIR=str(tmp_path), BENCH_RESULTS_DIR=str(tmp_path))
    r = subprocess.run([sys.executable, "-m", "runner", "synthetic", "--only", "typo"],
                       cwd=_bench(), capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "typo" in r.stderr and "night_walker" in r.stderr
    (tmp_path / "truth").mkdir()
    (tmp_path / "truth" / "real.json").write_text("{}")
    r = subprocess.run([sys.executable, "-m", "runner", "virat", "--only", "typo"],
                       cwd=_bench(), capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "unknown clip" in r.stderr and "real" in r.stderr


def test_detector_that_does_not_stop_is_an_error_row(monkeypatch):
    from runner import run_detector as rd

    class Stuck:
        def __init__(self, *a, **k): pass
        def start(self): pass
        def stop(self): pass
        def join(self, timeout=None): pass
        def is_alive(self): return True

    monkeypatch.setattr(rd, "MotionDetector", Stuck)
    rec = rd.run_stream("rtsp://x/y", DetectorSettings(), 0.01)
    assert rec.error == "detector thread did not stop"
    row = rd.score_recording("x", [], rec, DetectorSettings(), 0.01)
    assert row["error"] == "detector thread did not stop"


# ---- VIRAT report ----------------------------------------------------------

import os

NO_DATA = "No VIRAT data. Run: python -m virat.fetch --accept-virat-terms"


def _bench():
    return Path(__file__).resolve().parents[1]


def test_virat_cli_skips_without_data(tmp_path):
    env = dict(os.environ, BENCH_VIRAT_DIR=str(tmp_path))
    r = subprocess.run([sys.executable, "-m", "runner", "virat"], cwd=_bench(),
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == NO_DATA


def test_virat_totals():
    from runner.virat_run import totals
    rows = [
        {"scenario": "a", "truth": 2, "hits": 2, "misses": 0, "false_alarms": 1, "stuck": 0,
         "delays": [1.0, 3.0], "run_seconds": 1800.0, "passed": True},
        {"scenario": "b", "truth": 3, "hits": 1, "misses": 2, "false_alarms": 1, "stuck": 1,
         "delays": [2.0], "run_seconds": 1800.0, "passed": True},
    ]
    t = totals(rows)
    assert t["clips"] == 2 and t["truth"] == 5 and t["hits"] == 3
    assert t["hit_rate"] == pytest.approx(0.6)
    assert t["median_delay"] == pytest.approx(2.0)
    assert t["false_alarms"] == 2 and t["stuck"] == 1
    assert t["false_alarms_per_hour"] == pytest.approx(2.0)


def test_virat_report_has_totals_and_footer(tmp_path):
    from runner.virat_run import write_virat_report
    rows = [{"scenario": "a", "truth": 1, "hits": 1, "misses": 0, "false_alarms": 0, "stuck": 0,
             "lost": 0, "median_delay": 1.0, "fps": 10.0, "connect_offset": 3.0, "delays": [1.0],
             "run_seconds": 60.0, "passed": True, "connected": 1},
            {"scenario": "dead", "truth": 1, "run_seconds": 60.0, "passed": False,
             "connected": 0, "connect_offset": None, "delays": []}]
    write_virat_report(rows, str(tmp_path / "v.md"), str(tmp_path / "v.json"))
    md = (tmp_path / "v.md").read_text()
    assert "Truth comes from VIRAT object annotations (moving boxes only, > 2% of frame width per second); it starts up to ~1 s late and ignores very slow movers." in md
    assert "hit rate" in md and "false alarms per hour" in md
    dead = [ln for ln in md.splitlines() if ln.startswith("| dead")][0]
    assert "ERROR" in dead
    js = json.loads((tmp_path / "v.json").read_text())
    assert js["totals"]["clips"] == 2 and len(js["rows"]) == 2


def test_virat_cli_runs_a_fake_clip(tmp_path):
    """Happy path with a fake clip (not VIRAT data) written to the shared volume."""
    import av
    import numpy as np
    import uuid
    clip = f"FAKE_TEST_{uuid.uuid4().hex[:8]}"
    root = Path("/data/virat")
    results_dir = tmp_path / "res"
    video, truth = root / "videos" / f"{clip}.mp4", root / "truth" / f"{clip}.json"
    (root / "videos").mkdir(parents=True, exist_ok=True)
    (root / "truth").mkdir(parents=True, exist_ok=True)
    try:
        c = av.open(str(video), "w")
        s = c.add_stream("libx264", rate=15)
        s.width, s.height, s.pix_fmt = 320, 240, "yuv420p"
        rng = np.random.default_rng(1)
        for i in range(15 * 20):
            img = np.full((240, 320, 3), 60, np.uint8)
            if 150 <= i < 240:
                img[:, :] = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)
            for p in s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
        c.close()
        truth.write_text(json.dumps({"fps": 15.0, "width": 320, "truth": [[10.0, 16.0]]}))
        out = results_dir
        env = dict(os.environ, BENCH_RESULTS_DIR=str(out))
        r = subprocess.run([sys.executable, "-m", "runner", "virat", "--only", clip],
                           cwd=_bench(), capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stdout + r.stderr
        js = json.loads((out / "virat.json").read_text())
        assert js["totals"]["clips"] == 1
        row = js["rows"][0]
        assert row["scenario"] == clip and row["connected"] >= 1
        assert clip in (out / "virat.md").read_text()
    finally:
        video.unlink(missing_ok=True)
        truth.unlink(missing_ok=True)


def test_virat_list_clips_hides_fake_and_limit_rejects_zero(tmp_path, monkeypatch):
    from runner import virat_run
    (tmp_path / "truth").mkdir()
    for n in ("a", "FAKE_x"):
        (tmp_path / "truth" / f"{n}.json").write_text("{}")
    monkeypatch.setenv("BENCH_VIRAT_DIR", str(tmp_path))
    assert virat_run.list_clips() == ["a"]
    assert virat_run.list_clips("FAKE_x") == ["FAKE_x"]
    r = subprocess.run([sys.executable, "-m", "runner", "virat", "--limit", "0"],
                       cwd=_bench(), capture_output=True, text=True)
    assert r.returncode == 2 and "--limit" in r.stderr


def test_report_shows_error_cause(tmp_path):
    from runner.virat_run import write_virat_report
    write_virat_report([{"scenario": "d", "passed": False, "error": "never connected"}],
                       str(tmp_path / "v.md"), str(tmp_path / "v.json"))
    assert "ERROR: never connected" in (tmp_path / "v.md").read_text()
