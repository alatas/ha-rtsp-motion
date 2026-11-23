"""Synthetic camera scenarios with known ground truth (pure, no network).

Each scenario yields steps: an RGB frame (uint8 HxWx3), or a control step
(Pause, Reopen, Jump) that the publisher turns into stream behaviour.
Frames are cached and may be yielded more than once, so treat them as
read-only.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Callable, Iterator, Union

import numpy as np


@dataclass(frozen=True)
class Pause:
    seconds: float  # send nothing, keep the session open


@dataclass(frozen=True)
class Reopen:
    width: int
    height: int  # close the session, publish again at this size


@dataclass(frozen=True)
class Jump:
    seconds: float  # add to all following timestamps


Step = Union[np.ndarray, Pause, Reopen, Jump]


@dataclass(frozen=True)
class Expect:
    video_lost: int = 0  # exact number of video_lost events
    max_false_alarms: int = 0


@dataclass(frozen=True)
class Scenario:
    name: str
    fps: float
    width: int
    height: int
    duration: float
    truth: list  # list[tuple[float, float]], stream seconds (Pause counts, Jump doesn't)
    expect: Expect
    steps: Callable[[], Iterator[Step]]


BASE_W, BASE_H = 1280, 720
NOISE_SIGMA = 4
BG = 40
WALKER_W, WALKER_H, WALKER_Y = 120, 260, 200  # at 1280x720
WALKER_BOOST = 30
WALKER_SPEED = 3  # px per frame at 1280x720, 15 fps

# Clock: seven-segment digits inside x 900-1260, y 10-70 (the ignore area).
CLOCK_X, CLOCK_Y, CLOCK_W, CLOCK_H = 900, 10, 360, 60
_SEGS = {
    "a": (0, 0, 40, 8), "b": (32, 0, 8, 32), "c": (32, 28, 8, 32),
    "d": (0, 52, 40, 8), "e": (0, 28, 8, 32), "f": (0, 0, 8, 32),
    "g": (0, 26, 40, 8),
}
_DIGITS = ["abcdef", "bc", "abdeg", "abcdg", "bcfg", "acdfg", "acdefg", "abc",
           "abcdefg", "abcdfg"]


def _clock_mask(second: int) -> np.ndarray:
    mask = np.zeros((CLOCK_H, CLOCK_W), dtype=bool)
    text = f"{10 + second // 3600:02d}{second // 60 % 60:02d}{second % 60:02d}"
    x = 0
    for n, ch in enumerate(text):
        for seg in _DIGITS[int(ch)]:
            sx, sy, sw, sh = _SEGS[seg]
            mask[sy:sy + sh, x + sx:x + sx + sw] = True
        x += 50
        if n in (1, 3):  # colon
            mask[14:22, x + 6:x + 14] = True
            mask[38:46, x + 6:x + 14] = True
            x += 24
    return mask


class _Renderer:
    """Noisy backgrounds for one scenario. The noise repeats every second."""

    def __init__(self, name: str, fps: float):
        self._seed = zlib.crc32(name.encode())
        self._period = max(1, round(fps))
        self._pools: dict = {}
        self._cache: dict = {}
        self._masks: dict = {}

    def _pool(self, w: int, h: int) -> np.ndarray:
        if (w, h) not in self._pools:
            rng = np.random.default_rng(self._seed + w)
            noise = rng.normal(0, NOISE_SIGMA, (self._period, h, w))
            self._pools[(w, h)] = np.rint(noise).astype(np.int16)
        return self._pools[(w, h)]

    def background(self, w, h, level: int, tick: int, cache=True) -> np.ndarray:
        key = (w, h, level, tick % self._period)
        if cache and key in self._cache:
            return self._cache[key]
        gray = np.clip(self._pool(w, h)[tick % self._period] + level, 0, 255)
        rgb = np.repeat(gray.astype(np.uint8)[:, :, None], 3, axis=2)
        if cache:
            self._cache[key] = rgb
        return rgb

    def white(self, w, h) -> np.ndarray:
        key = (w, h, "white")
        if key not in self._cache:
            self._cache[key] = np.full((h, w, 3), 255, dtype=np.uint8)
        return self._cache[key]

    def clock(self, rgb: np.ndarray, second: int) -> np.ndarray:
        if second not in self._masks:
            self._masks[second] = _clock_mask(second)
        out = rgb.copy()
        region = out[CLOCK_Y:CLOCK_Y + CLOCK_H, CLOCK_X:CLOCK_X + CLOCK_W]
        region[self._masks[second]] = 255
        return out


def _draw_walker(rgb: np.ndarray, xp: float, scale: float) -> np.ndarray:
    h, w = rgb.shape[:2]
    bw, bh = round(WALKER_W * scale), round(WALKER_H * scale)
    x, y = round(xp * scale), round(WALKER_Y * scale)
    out = rgb.copy()
    region = out[y:y + bh, x:min(x + bw, w)]
    region[:] = np.clip(region.astype(np.int16) + WALKER_BOOST, 0, 255)
    return out


def _make(
    name: str,
    *,
    fps: float = 15,
    duration: float = 60,
    level: Callable[[int, int], int] = lambda tick, total: BG,
    cache_background: bool = True,
    walkers: tuple = (),
    walker_speed: float = WALKER_SPEED,
    events: dict | None = None,
    clock: bool = False,
    glitch: bool = False,
    truth: list | None = None,
    expect: Expect = Expect(),
) -> Scenario:
    total = round(duration * fps)
    schedule = {round(t * fps): evs for t, evs in (events or {}).items()}

    def steps() -> Iterator[Step]:
        r = _Renderer(name, fps)
        w, h = BASE_W, BASE_H
        pending = {k: list(v) for k, v in schedule.items()}
        tick = 0
        while tick < total:
            for ev in pending.pop(tick, ()):
                yield ev
                if isinstance(ev, Pause):
                    tick += round(ev.seconds * fps)
                elif isinstance(ev, Reopen):
                    w, h = ev.width, ev.height
            if tick >= total:
                break
            if glitch and tick % round(2 * fps) == round(fps):
                yield r.white(w, h)
                tick += 1
                continue
            rgb = r.background(w, h, level(tick, total), tick, cache_background)
            for t0, t1 in walkers:
                f0, f1 = round(t0 * fps), round(t1 * fps)
                if f0 <= tick < f1:
                    # position in 1280-wide coordinates, so it carries over a Reopen
                    xp = walker_speed * (tick - f0)
                    rgb = _draw_walker(rgb, xp, w / BASE_W)
            if clock:
                rgb = r.clock(rgb, int(tick / fps))
            yield rgb
            tick += 1

    return Scenario(name, fps, BASE_W, BASE_H, duration, truth or [], expect, steps)


def _static_steps() -> Iterator[Step]:
    img = np.full((BASE_H, BASE_W, 3), 128, dtype=np.uint8)
    while True:
        yield img


def _build() -> dict:
    ev = lambda **kw: kw
    scenarios = [
        Scenario("static", 15, BASE_W, BASE_H, float("inf"), [], Expect(), _static_steps),
        _make("quiet_night"),
        _make("night_walker", walkers=((20, 40),), truth=[(20, 40)]),
        _make("lights_on", duration=40, level=lambda t, n: BG if t < 300 else 120,
              truth=[(20, 21)]),
        _make("slow_dusk", level=lambda t, n: round(120 - 60 * t / n),
              cache_background=False),
        _make("clock_corner", clock=True),
        _make("glitch_burst", glitch=True),
        _make("freeze_short", events={20: [Pause(3)]}),
        _make("freeze_long", events={20: [Pause(25)]}, expect=Expect(video_lost=1)),
        _make("size_change", walkers=((10, 20), (40, 50)),
              events={15: [Reopen(1920, 1080)]}, truth=[(10, 20), (40, 50)]),
        _make("pts_back", walkers=((10, 15),), events={16: [Jump(-3600)]},
              truth=[(10, 15)]),
        _make("pts_forward", walkers=((10, 30),), events={20: [Jump(3600)]},
              truth=[(10, 30)]),
        _make("low_fps", fps=2, walkers=((20, 40),), walker_speed=22, truth=[(20, 40)]),
    ]
    return {s.name: s for s in scenarios}


SCENARIOS: dict = _build()
