"""Acquisition parameters from MeasurementParamsXML: laser, PMTs, objective, every param and axis,
and the stage rows the reader adds to the information panel."""
import h5py
import numpy as np

from mesc_io.reader import MescFile

XML = ('<Task Type="TaskResonantCommon" Version="1.0"><Devices>'
       '<Gear name="PMT_UG" type="PMT"><param name="channel_name" value="UG"/>'
       '<param name="reference_voltage" value="7.0e+01"/><param name="ad_invert" value="1"/></Gear>'
       '<Gear name="PMT_UR" type="PMT"><param name="channel_name" value="UR"/>'
       '<param name="reference_voltage" value="6.0e+01"/><param name="ad_invert" value="1"/></Gear>'
       '<Gear name="rPockelsCell" type="PockelsCell"><param name="onintensity" value="4.00018e+02"/></Gear>'
       '<GearShutter name="Sh1"><param name="OnOffState" value="0"/></GearShutter>'
       '<APTMotor name="Im" type="APTMotor"><param name="position" value="7.5e+01"/>'
       '<param name="position_raw" value="11"/></APTMotor></Devices>'
       '<Params><param name="objective_name" value="obj16x"/><param name="BitCompression" value="16"/>'
       '<param name="Pixelclock" value="4.0572573e+06"/></Params>'
       '<AxisControl><snapshot space="space1">'
       '<axis attribute="AttributePosition" id="VirtX" value="-543.8"/>'
       '<axis attribute="AttributePosition" id="VirtY" value="4641.27"/>'
       '<axis attribute="AttributePosition" id="VirtZ" value="-27212.42"/>'
       '<axis attribute="AttributeRelativePosition" id="SlowX" value="-245.03"/>'
       '<axis attribute="AttributeRelativePosition" id="SlowY" value="-1042.03"/>'
       '<axis attribute="AttributeRelativePosition" id="SlowZ" value="-40.36"/>'
       '<axis attribute="DisplayName" id="SlowZ" value="Slow Z \xb5m"/>'
       '</snapshot></AxisControl></Task>').encode("latin-1")


def _file(path, xml=XML):
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0/MUnit_0")
        u.create_dataset("Channel_0", data=np.zeros((3, 8, 8), np.uint16))
        if xml is not None:
            u.attrs["MeasurementParamsXML"] = np.array(xml, dtype=f"S{len(xml) + 1}")
    return path


def test_laser_pmt_objective_and_everything_else(tmp_path):
    with MescFile(_file(tmp_path / "a.mesc")) as m:
        u = m.units()[0]
    assert abs(u.laser_pockels - 400.018) < 1e-9
    assert u.pmt_reference_voltage == {"UG": 70.0, "UR": 60.0}
    assert u.laser_im_percent == 75.0                    # MESc's "Im %", the APTMotor named Im
    assert u.objective == "obj16x" and u.acquired_bits == 16
    a = u.acquisition
    assert a["task"] == "TaskResonantCommon"
    assert a["devices"]["Sh1"] == {"type": "GearShutter", "OnOffState": 0}
    assert a["params"]["Pixelclock"] == 4.0572573e6
    assert a["axes"]["SlowZ"]["DisplayName"] == "Slow Z µm"
    info = dict(u.info)
    assert info["Stage position (absolute)"] == "x = -543.8 µm, y = 4641.27 µm, z = -27212.4 µm"
    assert info["Stage position from the zero level"] == "x = -245.03 µm, y = -1042.03 µm, z = -40.36 µm"
    assert info["Pockels cell (on-intensity)"] == "400.02"
    assert info["PMT reference voltage"] == "UG 70, UR 60"
    assert info["Imaging attenuator (Im)"] == "75 %"
    assert info["Objective"] == "obj16x"


def test_no_xml_no_rows(tmp_path):
    with MescFile(_file(tmp_path / "b.mesc", xml=None)) as m:
        u = m.units()[0]
    assert u.laser_pockels is None and u.pmt_reference_voltage is None and u.objective is None
    assert u.laser_im_percent is None
    assert u.acquisition == {"task": "", "devices": {}, "params": {}, "axes": {}}
    assert not any(k.startswith(("Stage", "Pockels", "PMT")) for k, _ in u.info)


def test_the_viewer_hands_the_page_the_laser_and_pmt(tmp_path):
    """The Metadata panel shows them (0.7.1): the unit description the page reads carries both."""
    from mesc_io import viewer as V
    import threading, json, urllib.request
    path = _file(tmp_path / "acq.mesc")
    httpd = V.make_server(path, port=0, rois_path=tmp_path / "r.json")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        host, port = httpd.server_address[:2]
        with urllib.request.urlopen(f"http://{host}:{port}/api/file", timeout=5) as r:
            u = json.loads(r.read())["units"][0]
    finally:
        httpd.shutdown(); httpd.server_close()
    assert abs(u["laser_pockels"] - 400.018) < 1e-9
    assert u["pmt_reference_voltage"] == {"UG": 70.0, "UR": 60.0}
    assert u["laser_im_percent"] == 75.0
    assert "acquired_bits" in u


def test_a_unit_whose_metadata_cannot_be_read_is_skipped_not_fatal(tmp_path, monkeypatch):
    """A .mesc copied while MESc was still writing has a torn last unit ("incorrect metadata
    checksum", cm030 17.11.2026); the finished units must still open, with a warning."""
    import pytest
    from mesc_io import reader as R
    path = tmp_path / "torn.mesc"
    with h5py.File(path, "w") as f:
        for k in (0, 1):
            f.create_group(f"MSession_0/MUnit_{k}").create_dataset("Channel_0", data=np.zeros((3, 8, 8), np.uint16))
    real = R.MescFile._read_unit

    def torn(self, s, name):
        if name == "MUnit_1":
            raise RuntimeError("incorrect metadata checksum after all read attempts")
        return real(self, s, name)
    monkeypatch.setattr(R.MescFile, "_read_unit", torn)
    with pytest.warns(R.UnreadableUnitWarning, match="MUnit_1 skipped"):
        with MescFile(path) as m:
            assert [u.name for u in m.units()] == ["MUnit_0"]
