"""The two pieces the viewer replaced a library with, held against the library.

`mesc-io view` used to need Pillow (to write a PNG) and matplotlib (to ask whether a pixel is
inside a polygon). For a tool meant to run on a colleague's machine that is two more ways for
"it does not start" to happen, so both are now forty lines of stdlib and numpy. Which is only
defensible if it is checked against the thing it replaced — otherwise it is just less code that
nobody has verified.

The PNG test does NOT assert byte-identity with Pillow: zlib settings differ, so the bytes are
not the same. It asserts the thing that matters — Pillow decodes our PNG back to exactly the
pixels that went in.
"""
from __future__ import annotations

import io

import numpy as np
import pytest

from mesc_io.viewer import _in_polygon, _png_grau


def test_our_png_decodes_back_to_the_same_pixels():
    Image = pytest.importorskip("PIL.Image", reason="Pillow is the reference here")
    rng = np.random.RandomState(0)
    for shape in [(1, 1), (4, 4), (17, 31), (64, 64), (256, 256)]:
        a = rng.randint(0, 256, shape, dtype=np.uint8)
        back = np.array(Image.open(io.BytesIO(_png_grau(a))))
        assert back.shape == a.shape
        assert np.array_equal(back, a), f"{shape}: our PNG lost pixels"


def test_our_png_is_a_png_at_all():
    """No reference library needed: the magic, and a decodable IEND at the end."""
    data = _png_grau(np.zeros((3, 5), dtype=np.uint8))
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data.endswith(b"IEND\xae\x42\x60\x82")


def test_polygon_matches_matplotlib_on_random_shapes():
    MPath = pytest.importorskip("matplotlib.path", reason="matplotlib is the reference here").Path
    rng = np.random.RandomState(1)
    h, w = 40, 50
    for k in range(40):
        pts = rng.uniform(0, min(h, w), (rng.randint(3, 9), 2))
        yy, xx = np.mgrid[0:h, 0:w]
        ref = MPath(pts).contains_points(
            np.column_stack([xx.ravel(), yy.ravel()])).reshape(h, w)
        assert np.array_equal(_in_polygon(pts, h, w), ref), f"polygon {k} differs"


def test_a_square_contains_what_a_square_should():
    """A case that needs no reference at all, so the test still means something if
    matplotlib is absent."""
    mask = _in_polygon(np.array([[2.0, 2.0], [7.0, 2.0], [7.0, 6.0], [2.0, 6.0]]), 10, 10)
    assert mask[3, 3] and mask[5, 5]
    assert not mask[0, 0] and not mask[9, 9]
    assert not mask[1, 3], "a pixel above the top edge is outside"


def test_a_degenerate_polygon_does_not_crash():
    """Three points in a line have no interior; the viewer must not raise on a bad ROI."""
    mask = _in_polygon(np.array([[0.0, 0.0], [5.0, 0.0], [9.0, 0.0]]), 10, 10)
    assert mask.shape == (10, 10)
    assert not mask.any()
