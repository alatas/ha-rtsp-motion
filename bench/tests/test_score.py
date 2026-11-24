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


def test_short_change_can_be_caught_after_it_ends():
    # Detection takes compare + confirm + transport (~1.5 s), so a 1 s change is
    # only seen after it's over. The hit window stays open HIT_LATE s after the start.
    s = score([(20, 21)], [(21.4, 27)], 5)
    assert (s.hits, s.misses) == (1, 0)
    s = score([(20, 21)], [(23.5, 27)], 5)
    assert (s.hits, s.misses) == (0, 1)


def test_movement_during_an_ongoing_motion_is_covered():
    # The second movement starts while the motion fired by the first is still on:
    # there's no new start to match, but the motion was showing. Not a miss.
    s = score([(10, 15), (17, 20)], [(10.5, 26)], 5)
    assert (s.hits, s.covered, s.misses, s.stuck) == (1, 1, 0, 0)


def test_early_motion_does_not_cover_later_truth():
    # Only a motion that already hit real movement counts as covering the next one.
    s = score([(20, 40)], [(15.0, 45)], 5)
    assert (s.hits, s.covered, s.misses) == (0, 0, 1)


def test_truth_with_no_motion_is_miss():
    s = score([(20, 40)], [], 5)
    assert s.misses == 1
    assert s.hits == 0
