"""The unit as MESc's information panel lists it: every row worked out from the attributes behind it.

The numbers are those of the panel photographed on the rig on 2026-10-05 (a 256 x 256 time series),
put into a small file: the axes' offsets and steps, the stage translation, the zero level, the date."""
import datetime as dt

import h5py
import numpy as np
import pytest

from mesc_io.reader import MescFile, _euler_zxy_deg

TEXT = lambda s, dtype=np.uint8: np.array([ord(c) for c in s] + [0], dtype=dtype)


def _write(path, z_role=0, z_scale=16.15278373, n=4, rot=(0.0, 0.0, 0.0, 1.0)):
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0").create_group("MUnit_0")
        for c, name in ((0, "UG"), (1, "UR")):
            u.create_dataset(f"Channel_{c}", data=np.zeros((n, 16, 16), np.uint16))
            u.attrs[f"Channel_{c}_Name"] = TEXT(name)
            u.attrs[f"Channel_{c}_Conversion_ConversionLinearOffset"] = -786.0
            u.attrs[f"Channel_{c}_Conversion_ConversionLinearScale"] = 1.0
        for c, name in ((0, "UG"), (1, "UR")):
            u.create_group(f"Curve_{c}").attrs["Name"] = TEXT(name)
        a = u.attrs
        a["TypeDebugString"] = np.array([b"MImage3D"])
        when = dt.datetime(2026, 10, 5, 10, 36, 42).timestamp()      # local time, as the rig writes it
        a["MeasurementDatePosix"] = np.array([int(when)], np.uint64)
        a["MeasurementDateNanoSecs"] = np.array([707000000], np.uint32)
        a["CreatingMEScVersion"] = TEXT("MESc 4.0")
        a["CreatingMEScRevision"] = np.array([11606], np.uint32)
        a["ExperimenterProfilename"] = TEXT("measurement")
        a["ExperimenterUsername"] = TEXT("measurement")
        a["ExperimenterHostname"] = TEXT("RIG-PC")
        a["ExperimenterSetupID"] = TEXT("SETUP-1", np.int16)          # int16 text, as Femtonics writes this one
        a["MeasurementParamsXML"] = np.frombuffer(b'<Task Type="TaskResonantCommon" Version="1.0"></Task>', np.uint8)
        a["XDim"], a["YDim"], a["ZDim"] = (np.array([v], np.uint64) for v in (256, 256, 4953))
        for ax in "XY":
            a[f"{ax}AxisConversionConversionLinearScale"] = 0.449117647
            a[f"{ax}AxisConversionConversionLinearOffset"] = -57.26250172
        a["ZAxisConversionConversionLinearScale"] = z_scale
        a["ZAxisGeomRole"] = np.array([z_role], np.uint32)
        a["GeomTransTransl"] = np.array([0.0, 0.0, -26967.0])
        a["LabelingOriginTransl"] = np.array([0.0, 0.0, -26946.76])
        a["GeomTransRot"] = np.array(rot, float)
    return path


def _info(path):
    with MescFile(path) as f:
        return dict(f.units()[0].info), [k for k, _ in f.units()[0].info]


def test_the_rows_of_the_panel_photographed_on_the_rig(tmp_path):
    info, order = _info(_write(tmp_path / "t.mesc"))
    assert info["Item type"] == "Measurement"
    assert info["Date"] == "2026-10-05 10:36:42.707"
    assert (info["Creator"], info["Creator revision"]) == ("MESc 4.0", "11606")
    assert (info["Profile name"], info["User name"]) == ("measurement", "measurement")
    assert (info["Host name"], info["Setup name"]) == ("RIG-PC", "SETUP-1")
    assert info["Recorded I/O signals"] == info["Channels"] == "UG, UR"
    assert info["Measurement type"] == "Resonant XY scan time series"
    assert info["Dimensions"] == "256 × 256 × 4953"
    assert info["Bits per sample"] == "16"
    assert info["Size"] == "4.0 KiB"                     # what is on disk here: 2 channels x 4 x 16 x 16 x 2 B = 4096 B
    assert info["Pixel size"] == "0.449118 µm × 0.449118 µm"
    assert info["Scanning area"] == "114.974 µm × 114.974 µm"
    assert info["Centroid in absolute coordinates"] == "x = 0 µm, y = 0 µm, z = -26967 µm"
    assert info["Centroid from the zero level"] == "x = 0 µm, y = 0 µm, z = -20.24 µm"
    assert info["Rotation (ZX'Y\" Euler angles)"] == "0°, 0°, 0°"
    assert info["Frame rate"] == "61.9088 Hz"
    assert info["Duration"] == "1 min 20 s"
    assert order[:3] == ["Item type", "Date", "Creator"] and order[-2:] == ["Frame rate", "Duration"]


@pytest.mark.parametrize("axis, want", [(2, (30, 0, 0)), (0, (0, 30, 0)), (1, (0, 0, 30))])
def test_one_axis_rotations_come_out_as_that_angle(axis, want):
    q = [0.0, 0.0, 0.0, np.cos(np.radians(15))]
    q[axis] = np.sin(np.radians(15))
    assert np.allclose(_euler_zxy_deg(q), want, atol=1e-6)


def test_a_z_stack_gives_its_step_and_depth_not_a_frame_rate(tmp_path):
    info, _ = _info(_write(tmp_path / "z.mesc", z_role=3, z_scale=1.0))
    assert "Frame rate" not in info and "Duration" not in info
    assert info["Measurement type"] == "Resonant XY scan z-stack"
    assert (info["Slice step"], info["Depth"]) == ("1 µm", "4953 µm")


def test_a_unit_without_the_attributes_has_no_rows_rather_than_invented_ones(tmp_path):
    p = tmp_path / "bare.mesc"
    with h5py.File(p, "w") as f:
        f.create_group("MSession_0").create_group("MUnit_0").create_dataset("Channel_0", data=np.zeros((2, 4, 4), np.uint16))
    info, _ = _info(p)
    assert "Date" not in info and "Host name" not in info and "Centroid in absolute coordinates" not in info
