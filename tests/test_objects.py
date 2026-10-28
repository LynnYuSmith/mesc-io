"""Objects grown from a seed on the recording's own values (mesc_io.objects)."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from mesc_io import MescFile
from mesc_io import objects as O

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    out = tmp_path_factory.mktemp("obj") / "stack.mesc"
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_synthetic.py"), "--stack", str(out)],
                   check=True, capture_output=True)
    return out


def test_the_red_cell_is_one_compact_object_of_a_plausible_size(stack):
    # make_synthetic puts a red cell at (16, 30, 95), a Gaussian of sigma ~4.5 px across, ~2.6 slices deep
    with MescFile(stack) as f:
        u = f.units()[0]
        r = O.grow(f, u.path, 1, [16, 30, 95], 0.5, 15.0)
    assert abs(r["centre_vox"][0] - 16) <= 1.5 and abs(r["centre_vox"][1] - 30) <= 1.5 and abs(r["centre_vox"][2] - 95) <= 1.5
    assert 20 < r["um3"] < 400 and not r["stopped_at_max"]
    assert r["threshold"] == pytest.approx(r["background"] + 0.5 * (r["peak"] - r["background"]))
    assert {m["ch"] for m in r["means"]} == {0, 1} and r["means"][1]["v"] > 3 * r["means"][0]["v"]


def test_the_object_does_not_depend_on_any_display_window(stack):
    # the same seed and share: one answer (it was 86 to 834 µm³ on the page's window bytes)
    with MescFile(stack) as f:
        u = f.units()[0]
        a = O.grow(f, u.path, 1, [16, 30, 95], 0.5, 15.0)
        b = O.grow(f, u.path, 1, [16, 30, 95], 0.5, 15.0, down=2)
    assert a["n"] == b["n"] and a["um3"] == b["um3"]
    assert len(b["idx"]) <= len(a["idx"])          # the page's grid, reduced twice across


def test_the_radius_stops_it_and_says_so(stack):
    with MescFile(stack) as f:
        u = f.units()[0]
        small = O.grow(f, u.path, 1, [16, 30, 95], 0.2, 1.5)
        big = O.grow(f, u.path, 1, [16, 30, 95], 0.2, 15.0)
    assert small["reached_radius"] and small["n"] < big["n"]
    assert max(small["extent_um"]) <= 2 * 1.5 + 2 * max(u.pixel_size_um or 1, u.z_step_um)


def test_a_seed_outside_or_a_recording_is_refused(stack):
    with MescFile(stack) as f:
        u = f.units()[0]
        with pytest.raises(ValueError):
            O.grow(f, u.path, 0, [999, 0, 0], 0.5, 10.0)
        with pytest.raises(ValueError):
            O.grow(f, u.path, 0, [1, 1, 1], 1.5, 10.0)
