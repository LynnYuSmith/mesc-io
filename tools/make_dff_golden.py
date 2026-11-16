"""Freeze the calcium pipeline's own dF/F pieces into tests/data/dff_golden.npz.

mesc_io.dff is a numpy-only port of the pipeline's signal stage. tests/test_dff.py compares the
port with the pipeline when the pipeline is importable — on one machine only, so CI never saw a
drift. This writes the pipeline's answers on fixed inputs into the repo; tests/test_dff_golden.py
holds the port to them everywhere, and (where the pipeline is present) checks the file is still
what the pipeline gives today.

    python tools/make_dff_golden.py [--pipe ~/PycharmProjects/CalciumImagingPipeline/CalciumPipelineLib]

Needs the pipeline and its deps (scipy, peakutils, pandas). Rerun it only when the PIPELINE's
signal stage changes on purpose, and say so in the CHANGELOG.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "tests" / "data" / "dff_golden.npz"
FS = 61.88
N = 3000
SIGMAS = (1.0, 3.0, 5.0, 37.0)
WINDOWS = (5, 61, 3713)
QS = (0.3, 0.5, 0.1)


def inputs():
    rng = np.random.default_rng(20261116)
    t = np.arange(N) / FS
    trace = 300 + 40 * np.sin(t / 20) + 120 * (np.sin(t * 1.3) > 0.97) + rng.normal(0, 6, N)
    bg = 120 + 15 * np.sin(t / 17) + rng.normal(0, 3, N)
    m3 = trace * 0.6 + 40 + rng.normal(0, 4, N)
    img = rng.normal(500, 30, (64, 64))
    img[20:31, 30:41] -= 200
    return trace, bg, m3, img


def pipeline_answers(pipe: Path) -> dict:
    sys.path.insert(0, str(pipe))
    import pandas as pd
    import peakutils
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import savgol_filter
    from lib.io._helpers import _find_darkest_patch
    from lib.signals.filters import savgol_filter_per_unit
    from lib.signals.signal_processing import (bg_correct_per_unit, compute_dark_current_per_unit,
                                                compute_dff_for_groups, rolling_baseline,
                                                rolling_baselines_by_unit,
                                                subtract_dark_current_per_unit)
    trace, bg, m3, img = inputs()
    out = {"trace": trace, "bg": bg, "m3": m3, "img": img, "fs": np.float64(FS)}
    out["savgol_5_3"] = savgol_filter(trace, 5, 3, mode="nearest")
    for s in SIGMAS:
        out[f"gauss_{s:g}"] = gaussian_filter1d(bg, sigma=s, mode="nearest")
    out["poly5"] = peakutils.baseline(gaussian_filter1d(bg, 5.0, mode="nearest"), deg=5)
    for w in WINDOWS:
        out[f"rq_{w}"] = pd.Series(trace).rolling(w, center=True, min_periods=1).quantile(0.3).to_numpy()
    for q in QS:
        out[f"rb_{q:g}"] = np.asarray(rolling_baseline(trace, fps=FS, win_s=60.0, q=q), dtype=np.float64)
    out["darkest_10"] = np.asarray(_find_darkest_patch(img, win=10), dtype=np.int64)
    # the chain, in stage_signal's order, exactly as tests/test_dff.py runs it
    df = pd.DataFrame({"Mean1": bg.copy(), "Mean2": trace.copy(), "Mean3": m3.copy()})
    dc = compute_dark_current_per_unit({"u": df}, n_frames=10, col="Mean1")
    d = subtract_dark_current_per_unit({"u": df}, dc)
    d = savgol_filter_per_unit(d, window=5, polyorder=3, mean_prefix="Mean", in_place=True)
    d, _ = bg_correct_per_unit(d, sigma_baseline=5.0, baseline_degree=5, coef=0.8)
    b = rolling_baselines_by_unit(d, fps=FS, win_s=60.0, q=0.3, fps_by_unit={"u": FS})
    dff = compute_dff_for_groups(d, b, eps_pct=1.0, min_baseline_pct=5.0, nan_bad_rois=False)["u"]
    out["chain_Mean2"] = dff["Mean2"].to_numpy(dtype=np.float64)
    out["chain_Mean3"] = dff["Mean3"].to_numpy(dtype=np.float64)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pipe", type=Path,
                    default=Path.home() / "PycharmProjects/CalciumImagingPipeline/CalciumPipelineLib")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    ans = pipeline_answers(a.pipe)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, **ans)
    print(f"  {a.out}  ({a.out.stat().st_size // 1024} KB, {len(ans)} arrays)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
