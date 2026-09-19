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
HAVE_PIPE = False
IMPORT_ERROR = None
try:
    from scipy.signal import savgol_filter
    from scipy.ndimage import gaussian_filter1d
    import peakutils
    import pandas as pd
    from lib.signals.signal_processing import (rolling_baseline as pipe_rolling_baseline,
                                                bg_correct_per_unit, compute_dark_current_per_unit,
                                                subtract_dark_current_per_unit,
                                                rolling_baselines_by_unit, compute_dff_for_groups)
    from lib.signals.filters import savgol_filter_per_unit
    from lib.io._helpers import _find_darkest_patch
    HAVE_PIPE = True
except Exception as e:                             # noqa: BLE001
    IMPORT_ERROR = e

# A skip is honest only when the pipeline is genuinely absent. If it is on disk and will not
# import (the Python 3.12 circular import, a broken env), that is a FAILURE here: otherwise every
# "matches the pipeline" test passes by skipping on the one machine that could have run it.
if PIPE.exists() and not HAVE_PIPE:
    pytest.fail(f"the pipeline is at {PIPE} but does not import: {IMPORT_ERROR!r}", pytrace=False)

needs_pipe = pytest.mark.skipif(not HAVE_PIPE, reason="CalciumPipelineLib is not on this machine")

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


def test_the_dark_current_comes_off_the_first_live_frames_and_the_head_is_nan():
    bg = BG.copy(); bg[:10] = 7.0                      # ten dark frames: a black head
    # detected: the head is cut, dark comes from the first LIVE frames (the pipeline's frames
    # reach the signal stage trimmed, so its "first 10" are live too), the head is NaN
    r = D.compute_dff(TRACE, bg, FS)
    assert r.head == 10
    assert np.isnan(r.dff[0, :10]).all() and np.isfinite(r.dff[0, 10:]).all()
    assert r.dark == pytest.approx(float(BG[10:20].mean()), abs=1e-9)
    assert r.dff.shape[1] == N, "the frame axis must stay the movie's"
    # told there is no head: the ten dark frames ARE the dark current
    r0 = D.compute_dff(TRACE, bg, FS, head=0)
    assert r0.head == 0 and r0.dark == pytest.approx(7.0)


def test_dff_refuses_to_guess_a_frame_rate():
    with pytest.raises(ValueError):
        D.compute_dff(TRACE, BG, 0.0)
    with pytest.raises(ValueError):
        D.compute_dff(TRACE, BG, None)


# --- the CHAIN, not the pieces --------------------------------------------------------------
# Every piece can match and the chain still differ (it did: bg_coef, the unfiltered Mean1, the
# head in the fit -- found by the 2026-09-18 evaluation with a green suite). So this runs the
# pipeline's own stage functions on one DataFrame and compares compute_dff to them.

@needs_pipe
def test_the_chain_matches_stage_signal_on_the_same_traces():
    fs = FS
    # what extraction hands the signal stage: Mean1 = darkest patch, Mean2.. = ROIs, HEAD ALREADY TRIMMED
    mean1 = BG.copy()
    m2 = TRACE.copy(); m3 = TRACE * 0.6 + 40 + rng.normal(0, 4, N)
    df = pd.DataFrame({"Mean1": mean1, "Mean2": m2, "Mean3": m3})
    # --- the pipeline, in stage_signal's order (stages.py ~5123-5230, config defaults) ---
    dc = compute_dark_current_per_unit({"u": df}, n_frames=10, col="Mean1")
    d = subtract_dark_current_per_unit({"u": df}, dc)
    d = savgol_filter_per_unit(d, window=5, polyorder=3, mean_prefix="Mean", in_place=True)
    d, _bg = bg_correct_per_unit(d, sigma_baseline=5.0, baseline_degree=5, coef=0.8)
    b = rolling_baselines_by_unit(d, fps=fs, win_s=60.0, q=0.3, fps_by_unit={"u": fs})
    dff = compute_dff_for_groups(d, b, eps_pct=1.0, min_baseline_pct=5.0, nan_bad_rois=False)["u"]
    # --- the port, on the same raw traces ---
    r = D.compute_dff(np.vstack([m2, m3]), mean1, fs, D.DffParams(bg_coef=0.8), head=0)
    # the pipeline computes eps over Mean1 too; the port over the ROIs only. Feed it the same
    # column set so the comparison isolates the chain, not the eps scope.
    r_all = D.compute_dff(np.vstack([mean1, m2, m3]), mean1, fs, D.DffParams(bg_coef=0.8), head=0)
    for k, col in ((1, "Mean2"), (2, "Mean3")):
        ours, ref = r_all.dff[k], dff[col].to_numpy(dtype=float)
        # the pipeline stores the baseline as float32 (signal_processing.py:488): 1e-5, not 1e-9
        assert np.allclose(ours, ref, atol=2e-5, rtol=1e-5), f"{col}: max |Δ| = {np.abs(ours - ref).max():.2e}"
    assert r.eps > 0


@needs_pipe
def test_the_old_chain_would_have_failed_that():
    """The positive control: the three divergences the evaluation found, re-created on purpose,
    must NOT match. If this passes by accident the parity test above proves nothing."""
    fs = FS
    df = pd.DataFrame({"Mean1": BG.copy(), "Mean2": TRACE.copy()})
    dc = compute_dark_current_per_unit({"u": df}, n_frames=10, col="Mean1")
    d = subtract_dark_current_per_unit({"u": df}, dc)
    d = savgol_filter_per_unit(d, window=5, polyorder=3, mean_prefix="Mean", in_place=True)
    d, _ = bg_correct_per_unit(d, sigma_baseline=5.0, baseline_degree=5, coef=0.8)
    b = rolling_baselines_by_unit(d, fps=fs, win_s=60.0, q=0.3, fps_by_unit={"u": fs})
    ref = compute_dff_for_groups(d, b, eps_pct=1.0, min_baseline_pct=5.0, nan_bad_rois=False)["u"]["Mean2"].to_numpy()
    wrong = D.compute_dff(np.vstack([BG, TRACE]), BG, fs, D.DffParams(bg_coef=1.0), head=0).dff[1]
    assert not np.allclose(wrong, ref, atol=2e-5, rtol=1e-5), "coef 1.0 matched coef 0.8 -- the test cannot see the chain"
