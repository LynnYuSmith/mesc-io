"""The conversion limits: MESc clamps the RAW integers to each channel's Lower/UpperLimit
before scale + offset. Every recording we have seen states 0…65535 (a no-op), so the
fixture narrows them to make the clamp visible."""
import h5py
import numpy as np
import pytest

from mesc_io import MescFile, clamp_raw, to_reader_units
from mesc_io.viewer import _reduce

OFF = -786.0
LO, HI = 900, 1000


def _file(tmp_path, lo, hi, kind="Uint16"):
    path = tmp_path / f"limits_{lo}_{hi}.mesc"
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0/MUnit_0")
        u.create_dataset("Channel_0", data=(np.arange(8 * 4 * 4, dtype=np.uint16).reshape(8, 4, 4) * 10 + 800))
        u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = OFF
        u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
        if lo is not None:
            u.attrs[f"Channel_0_Conversion_LowerLimit{kind}"] = np.uint16(lo) if kind == "Uint16" else float(lo)
            u.attrs[f"Channel_0_Conversion_UpperLimit{kind}"] = np.uint16(hi) if kind == "Uint16" else float(hi)
        u.attrs["ZAxisConversionConversionLinearScale"] = 16.15
    return path


def _expected(raw):
    return np.clip(raw.astype(np.float64), LO, HI) + OFF


def test_the_raw_values_are_clamped_before_the_offset():
    raw = np.array([0, 899, 900, 950, 1000, 1001, 65535], dtype=np.uint16)
    got = to_reader_units(raw, offset=OFF, limits=(LO, HI))
    assert got.tolist() == [114.0, 114.0, 114.0, 164.0, 214.0, 214.0, 214.0]


def test_full_range_limits_change_nothing():
    raw = np.array([0, 786, 65535], dtype=np.uint16)
    assert np.array_equal(to_reader_units(raw, OFF, limits=(0, 65535)), to_reader_units(raw, OFF))
    assert clamp_raw(raw, (0, 65535)) is raw          # no copy, no pass


def test_halved_arrays_are_restored_then_clamped():
    halved = np.array([400, 500, 600], dtype=np.int16)   # raw 800, 1000, 1200
    assert to_reader_units(halved, OFF, halved=True, limits=(LO, HI)).tolist() == [114.0, 214.0, 214.0]


@pytest.mark.parametrize("kind", ["Uint16", "Double"])
def test_the_reader_applies_the_files_limits(tmp_path, kind):
    with MescFile(_file(tmp_path, LO, HI, kind)) as f:
        ch = f.unit("MUnit_0").channels[0]
        assert ch.limits == (LO, HI)
        raw = f.read("MUnit_0", reader_units=False)
        assert np.array_equal(f.read("MUnit_0"), _expected(raw))
        streamed = np.concatenate(list(f.iter_frames("MUnit_0", block=3)))
        assert np.array_equal(streamed, _expected(raw))


def test_a_file_without_limits_reads_as_before(tmp_path):
    with MescFile(_file(tmp_path, None, None)) as f:
        assert f.unit("MUnit_0").channels[0].limits is None
        raw = f.read("MUnit_0", reader_units=False)
        assert np.array_equal(f.read("MUnit_0"), raw.astype(np.float64) + OFF)


def test_the_viewers_mean_clamps_before_averaging(tmp_path):
    # mean of clamped values ≠ clamped mean: the fast integer path must clamp first
    with MescFile(_file(tmp_path, LO, HI)) as f:
        want = f.read("MUnit_0").mean(axis=0)
        got = _reduce(f, "MUnit_0", 0, slice(None), "mean")
        np.testing.assert_allclose(got, want, rtol=0, atol=1e-9)
        np.testing.assert_allclose(_reduce(f, "MUnit_0", 0, slice(None), "max"), f.read("MUnit_0").max(axis=0))
