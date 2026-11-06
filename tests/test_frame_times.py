"""Per-frame hardware stamps (``Curve_N/CurveDataYRawData``, clock ticks): the real frame times,
including the pause the nominal period leaves out."""
import h5py
import numpy as np
import pytest

from mesc_io import MescFile
from mesc_io.check import check

TICK_MS = 2e-5                     # 50 MHz clock
PERIOD_TICKS = 807_316             # 16.146 ms, not the nominal 16.153
N = 40


def _name(s):
    return np.array([ord(c) for c in s] + [0], dtype=np.int16)


def _stamps(n, pause_at=None, pause_ticks=31_000_000, extra=True):
    dt = np.full(n + (1 if extra else 0), PERIOD_TICKS, dtype=np.float64)
    if extra:
        dt[-1] = 20                                  # the end-of-acquisition near-duplicate
    if pause_at is not None:
        dt[pause_at] += pause_ticks                   # 0.62 s
    return np.cumsum(dt)


def _file(tmp_path, curves, zstack=False, n=N):
    path = tmp_path / "stamps.mesc"
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0/MUnit_0")
        for k, ch in enumerate(("UG", "UR")):
            u.create_dataset(f"Channel_{k}", data=np.zeros((n, 2, 2), dtype=np.uint16))
            u.attrs[f"Channel_{k}_Name"] = _name(ch)
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearOffset"] = -786.0
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearScale"] = 1.0
        u.attrs["ZAxisConversionConversionLinearScale"] = 16.15278
        if zstack:
            u.attrs["ZAxisGeomRole"] = np.uint32(3)
        # stored in reverse order on purpose: the curve is found by its name, not its position
        for k, (ch, y) in reversed(list(enumerate(curves))):
            c = u.create_group(f"Curve_{k}")
            c.attrs["Name"] = _name(ch)
            c.attrs["Comment"] = _name("INPUT;TIMESTAMP")
            c.attrs["CurveDataYConversionConversionLinearScale"] = TICK_MS
            c.attrs["CurveDataYConversionConversionLinearOffset"] = 0.0
            c.create_dataset("CurveDataYRawData", data=h5py.Empty("f8") if y is None else y)
    return path


def test_stamps_are_seconds_one_per_frame(tmp_path):
    ug, ur = _stamps(N), _stamps(N) + 50
    with MescFile(_file(tmp_path, [("UR", ur), ("UG", ug)])) as f:
        t = f.frame_times("MUnit_0")
        assert t.shape == (N,)
        np.testing.assert_allclose(t, ug[:N] * TICK_MS / 1000)
        np.testing.assert_allclose(f.frame_times("MUnit_0", channel=1), ur[:N] * TICK_MS / 1000)
        assert t[0] == pytest.approx(0.01614632)         # closes frame 0


def test_the_pause_is_found_and_timed(tmp_path):
    with MescFile(_file(tmp_path, [("UG", _stamps(N, pause_at=8)), ("UR", _stamps(N, pause_at=8))])) as f:
        (frame, lost), = f.frame_stalls("MUnit_0")
        assert frame == 8 and lost == pytest.approx(0.62)
        t = f.frame_times("MUnit_0")
        assert t[20] - 20 * 0.01615 > 0.6                # frame × period would put it 0.6 s early
    hits = [x for x in check(tmp_path / "stamps.mesc").findings if x.code == "acquisition-pause"]
    assert len(hits) == 1 and hits[0].units == ("MSession_0/MUnit_0 @frame 8",)


def test_regular_stamps_have_no_stalls_and_no_note(tmp_path):
    path = _file(tmp_path, [("UG", _stamps(N)), ("UR", _stamps(N))])
    with MescFile(path) as f:
        assert f.frame_stalls("MUnit_0") == []
    assert not [x for x in check(path).findings if x.code == "acquisition-pause"]


def test_a_zstack_keeps_an_empty_curve(tmp_path):
    with MescFile(_file(tmp_path, [("UG", None), ("UR", None)], zstack=True)) as f:
        assert f.frame_times("MUnit_0") is None and f.frame_stalls("MUnit_0") == []


def test_no_curves_means_no_stamps(tmp_path):
    with MescFile(_file(tmp_path, [])) as f:
        assert f.frame_times("MUnit_0") is None


def test_a_short_curve_is_returned_with_a_warning(tmp_path):
    with MescFile(_file(tmp_path, [("UG", _stamps(N - 5, extra=False)), ("UR", _stamps(N))])) as f:
        with pytest.warns(RuntimeWarning, match="35 stamps for 40 frames"):
            assert len(f.frame_times("MUnit_0")) == 35


def test_unnamed_channels_take_their_curves_by_position(tmp_path):
    # no Channel_N_Name and no curve Name: "" == "" must not hand channel 1 the curve of channel 0
    path = tmp_path / "unnamed.mesc"
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0/MUnit_0")
        for k in range(2):
            u.create_dataset(f"Channel_{k}", data=np.zeros((N, 2, 2), dtype=np.uint16))
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearOffset"] = -786.0
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearScale"] = 1.0
            c = u.create_group(f"Curve_{k}")
            c.attrs["CurveDataYConversionConversionLinearScale"] = TICK_MS
            c.create_dataset("CurveDataYRawData", data=_stamps(N) + 1000 * k)
        u.attrs["ZAxisConversionConversionLinearScale"] = 16.15278
    with MescFile(path) as f:
        d = f.frame_times("MUnit_0", channel=1) - f.frame_times("MUnit_0", channel=0)
    np.testing.assert_allclose(d, 1000 * TICK_MS / 1000)
