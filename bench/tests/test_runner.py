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
