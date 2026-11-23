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


@pytest.mark.xfail(strict=True, reason=(
    "integration finding: av.open blocks until video resumes, so the LOST_GRACE check "
    "never runs during a frozen-but-open session (no `lost` event)"))
def test_freeze_long_reports_lost_once():
    _sc, rec = _run("freeze_long")
    kinds = [e[1] for e in rec.events]
    assert rec.count("lost") == 1
    assert "connected" in kinds[kinds.index("lost"):]


def test_cli_writes_report():
    bench = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-m", "runner", "synthetic", "--only", "quiet_night"],
                       cwd=bench, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "quiet_night" in (bench / "results" / "synthetic.md").read_text()
    row = json.loads((bench / "results" / "synthetic.json").read_text())[0]
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
