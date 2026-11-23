from runner.score import ClipScore, score


def test_hit_with_delay():
    s = score([(20, 40)], [(21.0, 46.0)], 5)
    assert s == ClipScore(hits=1, misses=0, false_alarms=0, stuck=0, delays=[1.0])


def test_early_start_is_miss_not_false_alarm():
    s = score([(20, 40)], [(18.9, 45)], 5)
    assert s.hits == 0
    assert s.misses == 1
    assert s.false_alarms == 0


def test_motion_far_from_truth_is_false_alarm():
    s = score([], [(5, 10)], 5)
    assert s.false_alarms == 1
    assert s.hits == 0


def test_never_ending_motion_is_stuck():
    s = score([(10, 15)], [(10.5, None)], 5)
    assert s.hits == 1
    assert s.stuck == 1


def test_motion_ending_too_late_is_stuck():
    # last truth end 15 + hold 5 + 2.0 = 22; motion ends at 23
    s = score([(10, 15)], [(10.5, 23.0)], 5)
    assert s.hits == 1
    assert s.stuck == 1


def test_motion_ending_within_hold_is_not_stuck():
    s = score([(10, 15)], [(10.5, 22.0)], 5)
    assert s.stuck == 0


def test_never_ending_false_alarm_is_also_stuck():
    s = score([], [(50, None)], 5)
    assert s.false_alarms == 1
    assert s.stuck == 1


def test_finished_false_alarm_is_not_stuck():
    s = score([], [(50, 500)], 5)
    assert s.false_alarms == 1
    assert s.stuck == 0


def test_single_motion_counts_as_hit_for_one_truth_only():
    # motion start 10.2 lies inside both hit windows [9, 10.5] and [10, 12]
    s = score([(10, 10.5), (11, 12)], [(10.2, 10.8)], 5)
    assert s.hits == 1
    assert s.misses == 1
    assert s.false_alarms == 0


def test_truth_with_no_motion_is_miss():
    s = score([(20, 40)], [], 5)
    assert s.misses == 1
    assert s.hits == 0
