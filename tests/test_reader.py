import numpy as np
import pytest

from mesc_io import MescFile
from conftest import FRAME_PERIOD_MS, OFFSET_CH0, PIXEL_UM


def test_units_are_found_in_numeric_order(mesc):
    with MescFile(mesc) as f:
        assert [u.name for u in f.units()] == ["MUnit_0", "MUnit_1"]
        assert f.units()[0].shape == (12, 4, 4)


def test_the_frame_rate_is_the_reciprocal_of_the_stored_period(mesc):
    with MescFile(mesc) as f:
        u = f.unit("MUnit_0")
        assert u.frame_rate_hz == pytest.approx(61.909, abs=1e-3)
        assert u.duration_s == pytest.approx(12 * FRAME_PERIOD_MS / 1000.0, rel=1e-12)


def test_a_file_that_cannot_state_its_rate_says_None(mesc_without_rate):
    with MescFile(mesc_without_rate) as f:
        u = f.unit("MUnit_0")
        assert u.frame_rate_hz is None and u.duration_s is None


def test_pixel_size_comes_from_the_axis_conversion(mesc):
    with MescFile(mesc) as f:
        assert f.unit("MUnit_0").pixel_size_um == pytest.approx(PIXEL_UM)


def test_the_comment_is_returned_verbatim_and_unparsed(mesc):
    with MescFile(mesc) as f:
        assert f.unit("MUnit_1").comment == "second unit"


def test_channels_carry_their_own_offsets(mesc):
    with MescFile(mesc) as f:
        offs = [c.offset for c in f.unit("MUnit_0").channels]
        assert offs == [-786.0, -1170.0]


def test_reading_applies_the_channels_own_conversion(mesc):
    with MescFile(mesc) as f:
        stored = f.read("MUnit_0", channel=0, frames=slice(0, 1), reader_units=False)
        shown = f.read("MUnit_0", channel=0, frames=slice(0, 1))
        assert np.array_equal(shown, stored.astype(np.float64) + OFFSET_CH0)
        # the red channel must NOT be converted with the green channel's offset
        red = f.read("MUnit_0", channel=1, frames=slice(0, 1))
        assert np.array_equal(red, stored.astype(np.float64) - 1170.0)


def test_an_unknown_channel_names_what_there_is(mesc):
    with MescFile(mesc) as f:
        with pytest.raises(KeyError, match="Channel_0"):
            f.read("MUnit_0", channel=7)


def test_a_file_that_is_not_a_mesc_is_refused(tmp_path):
    import h5py
    p = tmp_path / "other.h5"
    with h5py.File(p, "w") as h:
        h.create_dataset("data", data=[1, 2, 3])
    from mesc_io import MescError
    with MescFile(p) as f:
        with pytest.raises(MescError, match="not a .mesc"):
            f.units()
