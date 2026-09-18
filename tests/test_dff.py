"""The viewer's dF/F against the pipeline's, piece by piece, on the same trace.

mesc_io.dff re-implements the signal stage's chain in numpy alone. A port that is not held
against the original is a second method with the same name, so each piece is compared to the
pipeline's own function when CalciumPipelineLib is importable on this machine, and the tests
are skipped — visibly — where it is not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from mesc_io import dff as D

PIPE = Path.home() / "PycharmProjects/CalciumImagingPipeline/CalciumPipelineLib"
if PIPE.exists() and str(PIPE) not in sys.path:
    sys.path.insert(0, str(PIPE))
try:
    from scipy.signal import savgol_filter
    from scipy.ndimage import gaussian_filter1d
    import peakutils
    import pandas as pd
    from lib.signals.signal_processing import rolling_baseline as pipe_rolling_baseline
    from lib.io._helpers import _find_darkest_patch
    HAVE_PIPE = True
except Exception:                                  # noqa: BLE001
    HAVE_PIPE = False

needs_pipe = pytest.mark.skipif(not HAVE_PIPE, reason="the pipeline (and scipy/peakutils) is not importable here")

rng = np.random.default_rng(1)
FS = 61.88
N = 3000
T = np.arange(N) / FS
# a trace with drift, a few events and noise -- the shape the real thing has
TRACE = 300 + 40 * np.sin(T / 20) + 120 * (np.sin(T * 1.3) > 0.97) + rng.normal(0, 6, N)
BG = 120 + 15 * np.sin(T / 17) + rng.normal(0, 3, N)


@needs_pipe
def test_savgol_matches_scipy_mode_nearest():
    ours = D.savgol(TRACE, 5, 3)
    ref = savgol_filter(TRACE, 5, 3, mode="nearest")
    assert np.allclose(ours, ref, atol=1e-9)


@needs_pipe
def test_gaussian_matches_scipy_mode_nearest():
    for sigma in (1, 3, 5.0, 37):
        assert np.allclose(D.gaussian1d(BG, sigma), gaussian_filter1d(BG, sigma=sigma, mode="nearest"), atol=1e-9)


@needs_pipe
def test_poly_baseline_matches_peakutils():
    y = gaussian_filter1d(BG, 5.0, mode="nearest")
    assert np.allclose(D.poly_baseline(y, 5), peakutils.baseline(y, deg=5), atol=1e-9)


@needs_pipe
def test_rolling_quantile_matches_pandas_centred_partial_windows():
    for w in (5, 61, 3713):
        ref = pd.Series(TRACE).rolling(w, center=True, min_periods=1).quantile(0.3).to_numpy()
        assert np.allclose(D.rolling_quantile(TRACE, w, 0.3), ref, atol=1e-9), w


@needs_pipe
def test_rolling_baseline_matches_the_pipelines():
    for q in (0.3, 0.5, 0.1):
        ours = D.rolling_baseline(TRACE, FS, 60.0, q, 0.05)
        ref = pipe_rolling_baseline(TRACE, fps=FS, win_s=60.0, q=q)
        assert np.allclose(ours, ref, atol=1e-9), q


@needs_pipe
def test_darkest_patch_matches_the_pipelines():
    img = rng.normal(500, 30, (256, 256)); img[40:60, 100:130] -= 200
    assert D.darkest_patch(img, 10) == _find_darkest_patch(img, win=10)


def test_black_head_is_found_and_absent():
    head = np.r_[np.full(6, 5.0), np.full(300, 120.0)] + rng.normal(0, 1, 306)
    assert D.black_head(head, FS) == 6
    assert D.black_head(np.full(300, 120.0) + rng.normal(0, 1, 300), FS) == 0


def test_the_chain_gives_zero_centred_dff_with_events_up():
    traces = np.vstack([TRACE, TRACE * 0.5 + 50])
    r = D.compute_dff(traces, BG, FS)
    assert r.dff.shape == (2, N)
    # q = 0.3 puts the baseline at the 30th percentile, so the median of dF/F sits a little
    # ABOVE zero (that is the point of 0.3 over 0.5: quiet noise mostly positive), not on it
    assert 0 <= np.median(r.dff[0][200:]) < 0.05
    assert r.dff[0].max() > 0.2                            # the events come out on top
    assert r.eps > 0 and np.isfinite(r.dff).all()


def test_the_dark_current_comes_off_the_background_first_frames():
    bg = BG.copy(); bg[:10] = 7.0
    r = D.compute_dff(TRACE, bg, FS)
    assert r.dark == pytest.approx(7.0)
