"""Score detected motions against ground-truth intervals. Pure Python."""
from dataclasses import dataclass

HIT_LEAD = 1.0        # a motion may start this long before the truth start and still hit
NEAR_MARGIN = 2.0     # +/- window for "near" (false-alarm and stuck overlap test)
STUCK_MARGIN = 2.0    # extra slack beyond hold before a motion counts as stuck


@dataclass
class ClipScore:
    hits: int
    misses: int
    false_alarms: int
    stuck: int
    delays: list[float]


def _near(truth: tuple[float, float], start: float, end: float | None) -> bool:
    """True if motion [start, end] comes within NEAR_MARGIN of truth. end None = open-ended."""
    t_start, t_end = truth
    if end is None:
        end = float("inf")
    return start <= t_end + NEAR_MARGIN and end >= t_start - NEAR_MARGIN


def score(truth: list[tuple[float, float]], motions: list[tuple[float, float | None]],
          hold: float) -> ClipScore:
    """Score motions against truth. A motion end of None means it never ended."""
    truths = sorted(truth)
    motions = sorted(motions, key=lambda m: m[0])
    claimed = [False] * len(motions)

    hits = misses = 0
    delays: list[float] = []
    for t_start, t_end in truths:
        match = None
        for i, (m_start, _m_end) in enumerate(motions):
            if claimed[i]:
                continue
            if t_start - HIT_LEAD <= m_start <= t_end:
                match = i
                break  # motions are sorted, so this is the earliest start in the window
        if match is None:
            misses += 1
        else:
            claimed[match] = True
            hits += 1
            delays.append(motions[match][0] - t_start)

    false_alarms = 0
    stuck = 0
    for m_start, m_end in motions:
        near = [t for t in truths if _near(t, m_start, m_end)]
        if not near:
            false_alarms += 1
            if m_end is None:
                stuck += 1
            continue
        if m_end is None:
            stuck += 1
            continue
        last_end = max(t_end for _t_start, t_end in near)
        if m_end > last_end + hold + STUCK_MARGIN:
            stuck += 1

    return ClipScore(hits=hits, misses=misses, false_alarms=false_alarms,
                     stuck=stuck, delays=delays)
