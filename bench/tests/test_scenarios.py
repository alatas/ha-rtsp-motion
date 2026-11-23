import numpy as np
import pytest

from fakecam.scenarios import SCENARIOS, Pause, Reopen

FINITE = [s for s in SCENARIOS.values() if s.name != "static"]


def _frames(scn, count=None):
    out = []
    for step in scn.steps():
        if isinstance(step, np.ndarray):
            out.append(step)
            if count is not None and len(out) >= count:
                break
    return out


def test_all_scenarios_present():
    assert set(SCENARIOS) == {
        "static", "quiet_night", "night_walker", "lights_on", "slow_dusk",
        "clock_corner", "glitch_burst", "freeze_short", "freeze_long",
        "size_change", "pts_back", "pts_forward", "low_fps",
    }


@pytest.mark.parametrize("scn", FINITE, ids=lambda s: s.name)
def test_every_scenario_frame_count(scn):
    frames = 0
    pause = 0.0
    for step in scn.steps():
        if isinstance(step, np.ndarray):
            frames += 1
        elif isinstance(step, Pause):
            pause += step.seconds
    assert abs(frames + pause * scn.fps - round(scn.duration * scn.fps)) <= 1


@pytest.mark.parametrize("scn", FINITE, ids=lambda s: s.name)
def test_frames_match_size(scn):
    w, h = scn.width, scn.height
    for step in scn.steps():
        if isinstance(step, Reopen):
            w, h = step.width, step.height
        elif isinstance(step, np.ndarray):
            assert step.dtype == np.uint8
            assert step.shape == (h, w, 3)


def test_static_is_flat_and_infinite():
    it = SCENARIOS["static"].steps()
    for _ in range(50):
        f = next(it)
        assert f.shape == (720, 1280, 3) and (f == 128).all()


def test_scenarios_repeat():
    a = _frames(SCENARIOS["quiet_night"], 5)
    b = _frames(SCENARIOS["quiet_night"], 5)
    assert all((x == y).all() for x, y in zip(a, b))


def test_clock_stays_in_ignore_area():
    frames = _frames(SCENARIOS["clock_corner"], 16)
    diff = frames[0].astype(int) != frames[15].astype(int)
    ys, xs = np.nonzero(diff.any(axis=2))
    assert len(xs) > 0
    assert xs.min() >= 832 and ys.max() < 86


def _changed(a, b):
    d = np.abs(a.astype(int) - b.astype(int)).max(axis=2)
    return (d > 15).mean()


def test_walker_only_inside_truth():
    frames = _frames(SCENARIOS["night_walker"])
    fps = SCENARIOS["night_walker"].fps
    at = lambda t: frames[int(t * fps)]
    assert _changed(at(10), at(15)) < 0.001
    assert _changed(at(25), at(30)) > 0.01
