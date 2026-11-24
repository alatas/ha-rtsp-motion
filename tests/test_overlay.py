"""Ignored-area drawing (pure numpy/PIL)."""
import numpy as np

from custom_components.rtsp_motion.overlay import draw_areas


def test_areas_are_darkened_and_outlined_rest_untouched():
    rgb = np.full((100, 200, 3), 200, np.uint8)
    out = draw_areas(rgb, [(0.5, 0.0, 0.5, 0.5)])
    assert out.shape == rgb.shape and out.dtype == np.uint8
    assert (out[:50, 100:] != 200).any()
    assert out[60:, :100].tolist() == rgb[60:, :100].tolist()  # outside: unchanged
    inside = out[10:40, 110:190].astype(int)
    assert inside.mean() < 140  # darkened (hatch lines add a little)
    assert tuple(out[0, 150]) == (255, 214, 0)  # yellow outline on the edge
    assert (rgb == 200).all()  # the input is not modified


def test_no_areas_without_grid_is_the_same_picture():
    rgb = np.random.default_rng(0).integers(0, 255, (72, 128, 3), dtype=np.uint8)
    assert (draw_areas(rgb, []) == rgb).all()


def test_areas_outside_or_empty_are_skipped():
    rgb = np.full((50, 50, 3), 100, np.uint8)
    out = draw_areas(rgb, [(1.0, 1.0, 0.5, 0.5), (0.2, 0.2, 0.0, 0.3)])
    assert (out == rgb).all()


def test_grid_marks_every_ten_percent():
    rgb = np.zeros((360, 640, 3), np.uint8)
    out = draw_areas(rgb, [], grid=True)
    for p in range(10, 100, 10):
        x = round(640 * p / 100)
        assert out[200, x].max() > 0, p  # a vertical line (below the labels)
    assert out[200, 33].max() == 0  # between lines stays dark
