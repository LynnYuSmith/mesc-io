import h5py
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


def _axis_unit(name):
    return np.array([ord(c) for c in name] + [0], dtype=np.uint8)


def _stack_and_recording(tmp_path):
    """One file holding a z-stack and a recording, each labelled the way MESc labels them."""
    path = tmp_path / "roles.mesc"
    with h5py.File(path, "w") as f:
        sess = f.create_group("MSession_0")
        for name, role, scale, unit in (("MUnit_0", 0, 32.30895437622263, "ms"),
                                        ("MUnit_1", 3, 1.0, "µm")):
            u = sess.create_group(name)
            u.create_dataset("Channel_0", data=np.zeros((4, 2, 2), dtype=np.uint16))
            u.attrs["ZAxisConversionConversionLinearScale"] = scale
            u.attrs["ZAxisGeomRole"] = role
            u.attrs["ZAxisConversionUnitName"] = _axis_unit(unit)
            u.attrs["XAxisConversionConversionLinearScale"] = 0.126171875
            u.attrs["YAxisConversionConversionLinearScale"] = 0.12629686820504823
    return path


def test_a_z_stack_is_not_given_a_frame_rate(tmp_path):
    """Its third axis is depth. Dividing 1000 by a 1 um slice spacing said "1000 Hz".

    That number is plausible, correctly typed, and would have gone into a rolling baseline and
    an event window without a murmur — five of the nine units of the 2026-09-24 calibration
    set were read that way.
    """
    with MescFile(_stack_and_recording(tmp_path)) as f:
        rec, stack = f.units()
        assert rec.frame_rate_hz == pytest.approx(30.951, abs=1e-3)
        assert rec.z_step_um is None
        assert stack.frame_rate_hz is None
        assert stack.z_step_um == pytest.approx(1.0)


def test_pixels_that_are_not_square_are_not_hidden(tmp_path):
    """Femtonics writes x and y separately and they are not always equal."""
    with MescFile(_stack_and_recording(tmp_path)) as f:
        u = f.units()[0]
        assert u.pixel_size_um == pytest.approx(0.126171875)
        assert u.pixel_size_y_um == pytest.approx(0.12629686820504823)


def test_square_pixels_leave_the_y_field_empty(mesc):
    """No second number to carry when the two agree — a caller reads pixel_size_um and stops."""
    with MescFile(mesc) as f:
        assert f.units()[0].pixel_size_y_um is None
