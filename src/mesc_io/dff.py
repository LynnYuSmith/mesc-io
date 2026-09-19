"""dF/F the way our pipeline computes it, in numpy alone, for the viewer's raw | dF/F switch.

The chain is the signal stage's, step for step (CalciumPipelineLib, ``stage_signal``):

    0. the head      — the pipeline's frames reach the signal stage with the black head
                       already trimmed. Here nothing is trimmed (the trace must stay aligned
                       with the movie), so every step below runs on frames ``head:`` and the
                       result is NaN over the head. Fitting the background WITH the head in it
                       bent the polynomial over the first few hundred live frames (2026-09-18
                       review) — greying the head hid the head, not its effect;
    1. dark current  — the mean of the first 10 frames of the darkest-patch trace, a scalar,
                       off every trace (Mean1 included);
    2. filter        — Savitzky–Golay, window 5, order 3, ``mode='nearest'``, on EVERY trace,
                       the darkest patch's included — the pipeline filters all ``Mean*``
                       columns and Mean1 is one of them (``lib/signals/filters.py``);
    3. background    — the filtered darkest-patch trace, Gaussian-smoothed (σ = 5 frames),
                       fitted with an iterative polynomial (degree 5; peakutils' algorithm),
                       **times ``bg_coef`` = 0.8** (the pipeline's default, which the sessions
                       do not override), subtracted from every trace;
    4. baseline      — rolling quantile q = 0.3, 60 s window, centred, partial windows at the
                       ends, then a Gaussian smooth of 5 % of the window; for q < 0.3 the
                       pipeline clamps under the signal AND floors the baseline at 1.0;
    5. dF/F          — (F − F0) / max(F0, eps), eps = max(1 % of the median baseline, the 1st
                       percentile of baselines) over the traces given.

Every piece here is a re-implementation without scipy, pandas or peakutils, so the viewer's
one dependency stays numpy. ``tests/test_dff.py`` holds each piece against the pipeline's own
function, AND the whole chain against ``bg_correct_per_unit`` → ``rolling_baselines_by_unit``
→ ``compute_dff_for_groups`` on one DataFrame, to the float32 bound the pipeline itself
imposes. A port whose pieces match and whose chain does not was exactly what the first
version was.

Still not the master's number, and said so: the ROI is whatever was drawn here (a 3-px disc,
not a Suite2p mask); eps is taken over the drawn ROIs, the pipeline takes it over the whole
area; the darkest patch is chosen on a 300-frame mean of unclipped raw frames, the pipeline on
the full motion-corrected mean of frames clipped at 0. Same method, this ROI, this patch.
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
    bg_coef: float = 0.8            # scripts/pipeline.py: bg_coef = 0.8; the sessions do not set it
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
                p: Optional[DffParams] = None, patch: tuple = (),
                head: Optional[int] = None) -> DffResult:
    """``traces`` (n_rois, n_frames) and the darkest patch's trace, both in reader units.

    ``head`` is the number of leading black-head frames; None means detect it from the
    darkest patch's trace. Everything is computed on frames ``head:`` — the pipeline sees
    those frames only — and the head comes back as NaN so it is never mistaken for signal.
    """
    p = p or DffParams()
    if not fs or fs <= 0:
        raise ValueError("dF/F needs the frame rate: the baseline window is in seconds")
    F_all = np.asarray(traces, float)
    if F_all.ndim == 1:
        F_all = F_all[None, :]
    bg_all = np.asarray(bg_trace, float)
    n_all = F_all.shape[1]
    h = int(black_head(bg_all, fs) if head is None else head)
    h = max(0, min(h, max(0, n_all - p.savgol_window)))
    # 0. the head is not the pipeline's input, so it is not this function's either
    F = F_all[:, h:]
    bg = bg_all[h:]
    n = F.shape[1]
    # 1. dark current: a scalar from the darkest patch's first (live) frames, off everything
    dark = float(bg[:p.dark_frames].mean()) if n else 0.0
    F = F - dark
    bg = bg - dark
    # 2. filter, per trace -- the darkest patch's trace too, as the pipeline does (it filters
    #    every Mean* column and Mean1 is one)
    if n >= p.savgol_window:
        F = np.vstack([savgol(t, p.savgol_window, p.savgol_order) for t in F])
        bg = savgol(bg, p.savgol_window, p.savgol_order)
    # 3. background: the smoothed, polynomial-fitted darkest-patch trace, scaled by bg_coef
    bgs = gaussian1d(bg, p.bg_sigma)
    background = poly_baseline(bgs, p.bg_degree) * p.bg_coef
    F = F - background[None, :]
    # 4. baseline; below q = 0.3 the pipeline also floors it at 1.0 (preprocessing.py)
    B = np.vstack([rolling_baseline(t, fs, p.window_s, p.quantile, p.smooth_frac) for t in F])
    if p.quantile < 0.3:
        B = np.maximum(B, 1.0)
    # 5. dF/F with the pipeline's floor
    valid = B[np.isfinite(B)]
    med = float(np.median(valid)) if valid.size else 1.0
    floor = max(float(np.percentile(valid, 1)) if valid.size else 1.0, 1e-6)
    eps = max(med * p.eps_pct / 100.0, floor)
    dff = (F - B) / np.maximum(B, eps)
    # back onto the movie's frame axis: the head is NaN, never a number
    pad = lambda a: np.concatenate([np.full(a.shape[:-1] + (h,), np.nan), a], axis=-1)
    return DffResult(dff=pad(dff), baseline=pad(B), corrected=pad(F), background=pad(background),
                     dark=dark, head=h, eps=eps, patch=tuple(patch))
