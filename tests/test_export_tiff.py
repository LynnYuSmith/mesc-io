"""The TIFF export is an ImageJ/Fiji hyperstack that opens with the scales, channels and notes the .mesc had."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

tifffile = pytest.importorskip("tifffile")

from mesc_io import MescFile
from mesc_io.export import to_tiff

ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    with tifffile.TiffFile(path) as t:
        x = t.pages[0].tags["XResolution"].value
        y = t.pages[0].tags["YResolution"].value
        return t.asarray(), t.series[0].axes, t.imagej_metadata, x[1] / x[0], y[1] / y[0]


def test_all_channels_make_one_composite_hyperstack(mesc, tmp_path):
    with MescFile(mesc) as f:
        out = to_tiff(f, "MUnit_0", tmp_path / "u0.tif", channel="all")
        ref = [f.read("MUnit_0", channel=k).astype(np.float32) for k in (0, 1)]
    a, axes, ij, um_x, um_y = _read(out)
    assert axes == "TCYX" and a.shape == (12, 2, 4, 4)
    assert np.array_equal(a[:, 0], ref[0]) and np.array_equal(a[:, 1], ref[1])
    assert ij["mode"] == "composite" and len(ij["LUTs"]) == 2
    assert len(ij["Ranges"]) == 4                         # one window per channel
    assert ij["finterval"] == pytest.approx(1 / 61.909, rel=1e-3)
    assert um_x == pytest.approx(0.439453125)
    assert "first unit" in ij["Info"] and "conversion_offset = -786" in ij["Info"]


def test_one_channel_stays_the_plain_stack_it_was(mesc, tmp_path):
    with MescFile(mesc) as f:
        out = to_tiff(f, "MUnit_0", tmp_path / "c1.tif", channel=1)
        ref = f.read("MUnit_0", channel=1).astype(np.float32)
    a, axes, ij, _, _ = _read(out)
    assert axes == "TYX" and np.array_equal(a, ref)
    assert ij.get("mode") != "composite"


def test_a_z_stack_carries_its_slice_spacing_not_a_frame_rate(tmp_path):
    stack = tmp_path / "stack.mesc"
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_synthetic.py"), "--stack", str(stack)],
                   check=True, capture_output=True)
    with MescFile(stack) as f:
        u = f.units()[0]
        out = to_tiff(f, u.name, tmp_path / "s.tif", channel="all")
    a, axes, ij, _, _ = _read(out)
    assert axes == "ZCYX" and a.shape[1] == 2
    assert ij["spacing"] == pytest.approx(u.z_step_um) and "finterval" not in ij
    lo0, hi0, lo1, hi1 = ij["Ranges"]
    assert hi1 > 5 * hi0                                  # the bright red does not set the green's window


def test_the_cli_writes_every_unit_into_a_folder(mesc, tmp_path):
    # in-process, as tests/test_cli.py does: a child process with a hand-built environment failed to
    # start Python at all on Windows (no SYSTEMROOT), which tested nothing of ours
    from mesc_io.__main__ import main
    out = tmp_path / "all"
    assert main(["export", str(mesc), "all", str(out), "--tiff"]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["synthetic_MUnit_0.tif", "synthetic_MUnit_1.tif"]
