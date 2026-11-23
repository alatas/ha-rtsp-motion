"""Motion truth from VIRAT objects.txt lines.

Columns: object id, duration, frame, x, y, w, h, type. Parked cars are
annotated too, so only boxes whose centre actually moves count.
"""
from collections import defaultdict
from typing import Iterable


def moving_intervals(
    lines: Iterable[str],
    fps: float,
    width: int,
    min_move: float = 0.02,
    merge_gap: float = 1.0,
    min_len: float = 0.5,
) -> list[tuple[float, float]]:
    lag = max(1, round(fps))
    limit = min_move * width
    tracks: dict[str, dict[int, tuple[float, float]]] = defaultdict(dict)
    for line in lines:
        p = line.split()
        if len(p) < 8:
            continue
        frame, x, y, w, h = (int(float(v)) for v in p[2:7])
        tracks[p[0]][frame] = (x + w / 2, y + h / 2)

    moving: set[int] = set()
    for t in tracks.values():
        for f, (cx, cy) in t.items():
            prev = t.get(f - lag)
            if prev is None:
                continue
            if ((cx - prev[0]) ** 2 + (cy - prev[1]) ** 2) ** 0.5 > limit:
                moving.add(f)
    if not moving:
        return []

    # runs of frames (each frame covers [f/fps, (f+1)/fps)), merged across short gaps
    runs: list[list[float]] = []
    for f in sorted(moving):
        s, e = f / fps, (f + 1) / fps
        if runs and s - runs[-1][1] < merge_gap:
            runs[-1][1] = e
        else:
            runs.append([s, e])
    return [(s, e) for s, e in runs if e - s >= min_len]
