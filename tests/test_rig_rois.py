"""ROIs drawn on the rig: ViewerParamsXML = base64 of a Qt QDataStream, with the ROI list a
second base64 stream inside it. The fixture ENCODES that format (big-endian Qt 5), so the test
does not depend on a recording."""
import base64
import json
import struct
import subprocess
import sys
import zipfile

import h5py
import numpy as np
import pytest

from mesc_io import MescFile, RigRoiWarning
from mesc_io.rig_rois import decode_rig_rois

PX = 0.439453125
OFF = -(256 - 1) / 2 * PX            # MESc: the offset is the centre of pixel 0


def qstr(s):
    b = s.encode("utf-16-be")
    return struct.pack(">I", len(b)) + b


def var(t, payload):
    return struct.pack(">IB", t, 0) + payload


V_BOOL = lambda v: var(1, bytes([v]))
V_INT = lambda v: var(2, struct.pack(">i", v))
V_LL = lambda v: var(4, struct.pack(">q", v))
V_DBL = lambda v: var(6, struct.pack(">d", v))
V_STR = lambda s: var(10, qstr(s))
V_UUID = lambda h: var(30, bytes.fromhex(h))
V_POINT = lambda x, y: var(26, struct.pack(">dd", x, y))
V_COLOR = lambda r, g, b: var(67, bytes([1]) + struct.pack(">5H", 0xFFFF, r * 257, g * 257, b * 257, 0))
V_POLY = lambda pts: var(86, struct.pack(">I", len(pts)) + b"".join(struct.pack(">dd", *p) for p in pts))


def roi_record(label, pts_um, colour=(0, 255, 255), order=0, extra=b"", extra_n=0):
    fields = [("label", V_STR(label)), ("polygonF", V_POLY(pts_um)), ("color", V_COLOR(*colour)),
              ("firstZPlane", V_INT(0)), ("lastZPlane", V_INT(0)), ("polyType", V_INT(0)),
              ("roiRole", V_INT(0)), ("visible", V_BOOL(1)), ("order", V_LL(order)),
              ("uniqueID", V_UUID("ab" * 16)), ("regularPolygonCenter", V_POINT(0.0, 0.0))]
    body = struct.pack(">I", len(fields) + extra_n) + b"".join(qstr(k) + v for k, v in fields) + extra
    return bytes.fromhex("cd" * 16) + struct.pack(">I", len(body)) + body


def viewer_params(records):
    inner = base64.b64encode(struct.pack(">I", len(records)) + b"".join(records)).decode()
    entries = [("Global", V_INT(0)), ("sectionIdxSpinBox_valueChanged(int)", V_INT(12)),
               ("ROI_sigUpdateROI(QString)", V_STR(inner)),
               ("meanWidget:fromTimeSpinBox_valueChanged(double)", V_DBL(0.0))]
    outer = struct.pack(">I", len(entries)) + b"".join(qstr(k) + v for k, v in entries)
    return np.frombuffer(base64.b64encode(outer), dtype=np.uint8)


def square(cx_px, cy_px, half=3):
    xs = [OFF + (cx_px + d) * PX for d in (-half, half)]
    ys = [OFF + (cy_px + d) * PX for d in (-half, half)]
    return [(xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]), (xs[0], ys[1]), (xs[0], ys[0])]


def _file(tmp_path, records):
    path = tmp_path / "rois.mesc"
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0/MUnit_0")
        u.create_dataset("Channel_0", data=np.zeros((3, 256, 256), dtype=np.uint16))
        u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = -786.0
        u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
        u.attrs["ZAxisConversionConversionLinearScale"] = 16.15
        for ax in "XY":
            u.attrs[f"{ax}AxisConversionConversionLinearOffset"] = OFF
            u.attrs[f"{ax}AxisConversionConversionLinearScale"] = PX
        if records is not None:
            u.attrs["ViewerParamsXML"] = viewer_params(records)
    return path


def test_rois_come_back_in_um_and_pixels_in_drawing_order(tmp_path):
    recs = [roi_record("2", square(200, 40), (255, 0, 255), order=20),
            roi_record("1", square(100, 150), order=10)]
    with MescFile(_file(tmp_path, recs)) as f:
        r1, r2 = f.rig_rois("MUnit_0")
    assert (r1.label, r2.label) == ("1", "2")
    np.testing.assert_allclose(r1.polygon_px[:-1].mean(axis=0), [100, 150], atol=1e-9)
    np.testing.assert_allclose(r1.polygon_px[0], [97, 147], atol=1e-9)
    np.testing.assert_allclose(r1.polygon_um, square(100, 150))
    assert r2.colour == "#ff00ff" and r1.visible is True and r1.uuid == "ab" * 16


def test_no_saved_state_means_no_rois(tmp_path):
    with MescFile(_file(tmp_path, None)) as f:
        assert f.rig_rois("MUnit_0") == []
    with MescFile(_file(tmp_path, [])) as f:
        assert f.rig_rois("MUnit_0") == []


def test_an_unknown_field_skips_that_roi_only(tmp_path):
    odd = roi_record("1", square(50, 50), order=1, extra=qstr("mystery") + var(999, b""), extra_n=1)
    with MescFile(_file(tmp_path, [odd, roi_record("2", square(60, 60), order=2)])) as f:
        with pytest.warns(RigRoiWarning, match="ROI 1 of 2 skipped"):
            got = f.rig_rois("MUnit_0")
    assert [r.label for r in got] == ["2"]


def test_garbage_is_not_an_exception():
    assert decode_rig_rois(np.frombuffer(b"not base64 at all!!", dtype=np.uint8)) == []
    assert decode_rig_rois(None) == []


def test_cli_lists_and_exports(tmp_path):
    pytest.importorskip("roifile")
    import roifile
    path = _file(tmp_path, [roi_record("1", square(100, 150), order=1)])
    run = lambda *a: subprocess.run([sys.executable, "-m", "mesc_io", "rig-rois", str(path), *a],
                                    capture_output=True, text=True, check=True).stdout
    assert "1 ROI(s) drawn on the rig" in run() and "x=100.0 y=150.0" in run()
    run("--out", str(tmp_path / "r.json"))
    (j,) = json.loads((tmp_path / "r.json").read_text())
    assert j["unit"] == "MSession_0/MUnit_0" and len(j["polygon_px"]) == 5
    run("--out", str(tmp_path / "r.zip"))
    with zipfile.ZipFile(tmp_path / "r.zip") as zf:
        assert zf.namelist() == ["1.roi"]
    (ij,) = roifile.roiread(str(tmp_path / "r.zip"))
    np.testing.assert_allclose(ij.coordinates().min(axis=0), [97.5, 147.5], atol=1e-4)   # corners


def test_the_zip_keeps_every_roi_when_labels_repeat(tmp_path):
    pytest.importorskip("roifile")
    recs = [roi_record("1", square(50, 50), order=1), roi_record("1", square(150, 150), order=2)]
    path = _file(tmp_path, recs)
    subprocess.run([sys.executable, "-m", "mesc_io", "rig-rois", str(path), "--out", str(tmp_path / "d.zip")],
                   check=True, capture_output=True)
    with zipfile.ZipFile(tmp_path / "d.zip") as zf:
        assert sorted(zf.namelist()) == ["1.roi", "1_2.roi"]
