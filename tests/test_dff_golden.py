"""The port held to the pipeline's frozen answers — on every machine, CI included.

tests/test_dff.py compares mesc_io.dff with the pipeline live, where the pipeline is importable
(one machine). tests/data/dff_golden.npz holds the pipeline's own answers on fixed inputs
(tools/make_dff_golden.py), so the port cannot drift from them unseen. The last test checks that
the file is still what the pipeline gives today, where the pipeline is present."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from mesc_io import dff as D

GOLDEN = Path(__file__).parent / "data" / "dff_golden.npz"
TOOLS = Path(__file__).resolve().parents[1] / "tools"


@pytest.fixture(scope="module")
def g():
    with np.load(GOLDEN, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def test_savgol(g):
    assert np.allclose(D.savgol(g["trace"], 5, 3), g["savgol_5_3"], atol=1e-9)


@pytest.mark.parametrize("sigma", [1.0, 3.0, 5.0, 37.0])
def test_gaussian(g, sigma):
    assert np.allclose(D.gaussian1d(g["bg"], sigma), g[f"gauss_{sigma:g}"], atol=1e-9)


def test_poly_baseline(g):
    assert np.allclose(D.poly_baseline(D.gaussian1d(g["bg"], 5.0), 5), g["poly5"], atol=1e-9)


@pytest.mark.parametrize("w", [5, 61, 3713])
def test_rolling_quantile(g, w):
    assert np.allclose(D.rolling_quantile(g["trace"], w, 0.3), g[f"rq_{w}"], atol=1e-9)


@pytest.mark.parametrize("q", [0.3, 0.5, 0.1])
def test_rolling_baseline(g, q):
    ours = D.rolling_baseline(g["trace"], float(g["fs"]), 60.0, q, 0.05)
    assert np.allclose(ours, g[f"rb_{q:g}"], atol=1e-9)


def test_darkest_patch(g):
    assert tuple(D.darkest_patch(g["img"], 10)) == tuple(int(v) for v in g["darkest_10"])


def test_the_chain(g):
    """The whole signal stage on Mean1 (background) + two ROIs, as stage_signal runs it."""
    r = D.compute_dff(np.vstack([g["bg"], g["trace"], g["m3"]]), g["bg"], float(g["fs"]),
                      D.DffParams(bg_coef=0.8), head=0)
    for k, col in ((1, "chain_Mean2"), (2, "chain_Mean3")):
        # the pipeline keeps its baseline as float32: 1e-5, not 1e-9 (as in test_dff.py)
        assert np.allclose(r.dff[k], g[col], atol=2e-5, rtol=1e-5), col


def test_the_chain_check_can_fail(g):
    """The control: the wrong background coefficient must not pass."""
    wrong = D.compute_dff(np.vstack([g["bg"], g["trace"]]), g["bg"], float(g["fs"]),
                          D.DffParams(bg_coef=1.0), head=0).dff[1]
    assert not np.allclose(wrong, g["chain_Mean2"], atol=2e-5, rtol=1e-5)


def test_the_frozen_file_is_still_the_pipelines(g):
    """Where the pipeline is importable: its answers today equal the frozen ones. If this fails the
    PIPELINE changed — rerun tools/make_dff_golden.py on purpose and say so in the CHANGELOG."""
    pipe = Path.home() / "PycharmProjects/CalciumImagingPipeline/CalciumPipelineLib"
    if not pipe.exists():
        pytest.skip("CalciumPipelineLib is not on this machine")
    sys.path.insert(0, str(TOOLS))
    try:
        import make_dff_golden as M
        now = M.pipeline_answers(pipe)
    finally:
        sys.path.remove(str(TOOLS))
    assert set(now) == set(g)
    for k, v in now.items():
        assert np.array_equal(np.asarray(v), g[k]), k
