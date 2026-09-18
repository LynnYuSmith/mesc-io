"""dF/F the way our pipeline computes it, in numpy alone, for the viewer's raw | dF/F switch.

The chain is the signal stage's, step for step (CalciumPipelineLib, ``stage_signal``):

    1. dark current  — the mean of the first 10 frames of the darkest-patch trace, a scalar,
                       off every trace (the shutter is still closed there);
    2. filter        — Savitzky–Golay, window 5, order 3, ``mode='nearest'``;
    3. background    — the darkest 10×10 patch's trace, Gaussian-smoothed (σ = 5 frames),
                       fitted with an iterative polynomial (degree 5; peakutils' algorithm),
                       subtracted from every trace;
    4. baseline      — rolling quantile q = 0.3, 60 s window, centred, partial windows at the
                       ends, then a Gaussian smooth of 5 % of the window; no clamp at q ≥ 0.3;
    5. dF/F          — (F − F0) / max(F0, eps), eps = max(1 % of the median baseline, the 1st
                       percentile of baselines).

Every piece here is a re-implementation without scipy, pandas or peakutils, so the viewer's
one dependency stays numpy. ``tests/test_dff.py`` holds each against the pipeline's own
function on the same trace when the pipeline is importable, so the port cannot drift.

What is NOT reproduced, on purpose: the leading trim. The viewer keeps every frame so the
trace stays aligned with the movie; the black head is instead handed back as ``head`` so the
page can grey it out. And the ROI itself is whatever was drawn here — a 3-px disc, not a
Suite2p mask — so the numbers are the method's, on this ROI, not the master's.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class DffParams:
    dark_frames: int = 10
    savgol_window: int = 5
    savgol_order: int = 3
    bg_patch: int = 10
    bg_sigma: float = 5.0
    bg_degree: int = 5
    bg_coef: float = 1.0
    quantile: float = 0.3
    window_s: float = 60.0
    smooth_frac: float = 0.05
    eps_pct: float = 1.0


# --- the pieces ------------------------------------------------------------------------------

def savgol(y: np.ndarray, window: int, order: int) -> np.ndarray:
    """Savitzky–Golay as scipy does it with ``mode='nearest'``: the least-squares kernel by
    a pseudo-inverse of the Vandermonde matrix, applied to an edge-replicated signal."""
    y = np.asarray(y, float)
    if window % 2 == 0:
        window += 1
    if window <= order or y.size < window:
        return y.copy()
    half = window // 2
    x = np.arange(-half, half + 1, dtype=float)
    A = np.vander(x, order + 1, increasing=True)
    coef = np.linalg.pinv(A)[0]                  # the row that evaluates the fit at x = 0
    padded = np.pad(y, half, mode="edge")
    return np.convolve(padded, coef[::-1], mode="valid")


def gaussian1d(y: np.ndarray, sigma: float) -> np.ndarray:
    """scipy's gaussian_filter1d with ``mode='nearest'``: truncate at 4σ, normalised kernel,
    edges replicated."""
    y = np.asarray(y, float)
    if sigma <= 0:
        return y.copy()
    r = int(4.0 * sigma + 0.5)
    x = np.arange(-r, r + 1, dtype=float)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    padded = np.pad(y, r, mode="edge")
    return np.convolve(padded, k[::-1], mode="valid")


def poly_baseline(y: np.ndarray, deg: int, max_it: int = 100, tol: float = 1e-3) -> np.ndarray:
    """peakutils.baseline, line for line: an iterative polynomial fit in which every point
    above the fit is pulled down to it, until the coefficients stop moving."""
    y = np.asarray(y, float).copy()
    order = deg + 1
    coeffs = np.ones(order)
    cond = abs(y).max() ** (1.0 / order) if abs(y).max() > 0 else 1.0
    x = np.linspace(0.0, cond, y.size)
    base = y.copy()
    vander = np.vander(x, order)
    pinv = np.linalg.pinv(vander)
    for _ in range(max_it):
        new = pinv @ y
        if np.linalg.norm(new - coeffs) / np.linalg.norm(coeffs) < tol:
            break
        coeffs = new
        base = vander @ coeffs
        y = np.minimum(y, base)
    return base


def rolling_quantile(y: np.ndarray, w: int, q: float) -> np.ndarray:
    """pandas ``rolling(w, center=True, min_periods=1).quantile(q)`` — the window shrinks at
    the ends instead of padding, and the quantile is linear-interpolated like numpy's."""
    y = np.asarray(y, float)
    n = y.size
    half = w // 2
    out = np.empty(n)
    # the middle, vectorised; the ends, one by one (they are few)
    if n >= w:
        from numpy.lib.stride_tricks import sliding_window_view
        mid = np.quantile(sliding_window_view(y, w), q, axis=1)
        out[half:half + mid.size] = mid
        for i in range(half):
            out[i] = np.quantile(y[:i + half + 1], q)
        for i in range(half + mid.size, n):
            out[i] = np.quantile(y[i - half:], q)
    else:
        for i in range(n):
            out[i] = np.quantile(y[max(0, i - half):i + half + 1], q)
    return out


def rolling_baseline(y: np.ndarray, fs: float, win_s: float, q: float, smooth_frac: float) -> np.ndarray:
    """The pipeline's ``rolling_baseline``: rolling quantile, Gaussian smooth of
    ``smooth_frac`` of the window, clamped under the signal only for q < 0.3."""
    w = max(5, int(round(win_s * fs)))
    if w % 2 == 0:
        w += 1
    bl = rolling_quantile(y, w, q)
    bl = gaussian1d(bl, max(1, int(round(w * smooth_frac))))
    if q < 0.3:
        bl = np.minimum(bl, np.asarray(y, float))
    return bl


def darkest_patch(mean_img: np.ndarray, win: int) -> tuple:
    """(y0, x0, y1, x1) of the darkest ``win``×``win`` window of the mean image — the
    pipeline's ``_find_darkest_patch``, with a box-sum instead of convolve2d."""
    h, w = mean_img.shape
    wh, ww = min(win, h), min(win, w)
    c = np.cumsum(np.cumsum(np.pad(mean_img, ((1, 0), (1, 0))), axis=0), axis=1)
    sums = c[wh:, ww:] - c[:-wh, ww:] - c[wh:, :-ww] + c[:-wh, :-ww]
    iy, ix = np.unravel_index(int(np.argmin(sums)), sums.shape)
    return int(iy), int(ix), int(iy + wh), int(ix + ww)


def black_head(bg_trace: np.ndarray, fs: float) -> int:
    """How many leading frames are the black head. The darkest patch's trace is at its
    dark-current floor there; the head ends where it first climbs clearly above it. 0 when
    the recording opens live."""
    y = np.asarray(bg_trace, float)
    if y.size < 20:
        return 0
    floor = np.median(y[:5])
    body = np.median(y[y.size // 4:])
    if body - floor < 3 * (np.std(y[y.size // 4:]) + 1e-9):
        return 0
    above = np.nonzero(y > floor + 0.5 * (body - floor))[0]
    return int(above[0]) if above.size else 0


# --- the chain -------------------------------------------------------------------------------

@dataclass
class DffResult:
    dff: np.ndarray            # (n_rois, n_frames)
    baseline: np.ndarray       # F0, same shape, after dark and background
    corrected: np.ndarray      # F after dark, filter and background
    background: np.ndarray     # the subtracted background trace (n_frames,)
    dark: float
    head: int                  # leading frames that are the black head
    eps: float
    patch: tuple               # (y0, x0, y1, x1) of the darkest patch


def compute_dff(traces: np.ndarray, bg_trace: np.ndarray, fs: float,
                p: Optional[DffParams] = None, patch: tuple = ()) -> DffResult:
    """``traces`` (n_rois, n_frames) and the darkest patch's trace, both in reader units."""
    p = p or DffParams()
    F = np.asarray(traces, float)
    if F.ndim == 1:
        F = F[None, :]
    bg = np.asarray(bg_trace, float)
    n = F.shape[1]
    # 1. dark current: a scalar from the darkest patch's first frames, off everything
    dark = float(bg[:p.dark_frames].mean()) if n else 0.0
    F = F - dark
    bg = bg - dark
    # 2. filter, per trace
    F = np.vstack([savgol(t, p.savgol_window, p.savgol_order) for t in F]) if n >= p.savgol_window else F
    # 3. background: the smoothed, polynomial-fitted darkest-patch trace
    bgs = gaussian1d(bg, p.bg_sigma)
    background = poly_baseline(bgs, p.bg_degree) * p.bg_coef
    F = F - background[None, :]
    # 4. baseline
    B = np.vstack([rolling_baseline(t, fs, p.window_s, p.quantile, p.smooth_frac) for t in F])
    # 5. dF/F with the pipeline's floor
    valid = B[np.isfinite(B)]
    med = float(np.median(valid)) if valid.size else 1.0
    floor = max(float(np.percentile(valid, 1)) if valid.size else 1.0, 1e-6)
    eps = max(med * p.eps_pct / 100.0, floor)
    dff = (F - B) / np.maximum(B, eps)
    return DffResult(dff=dff, baseline=B, corrected=F, background=background, dark=dark,
                     head=black_head(bg_trace, fs), eps=eps, patch=tuple(patch))
