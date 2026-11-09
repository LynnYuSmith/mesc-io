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
       '<GearShutter name="Sh1"><param name="OnOffState" value="0"/></GearShutter></Devices>'
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
    assert info["Objective"] == "obj16x"


def test_no_xml_no_rows(tmp_path):
    with MescFile(_file(tmp_path / "b.mesc", xml=None)) as m:
        u = m.units()[0]
    assert u.laser_pockels is None and u.pmt_reference_voltage is None and u.objective is None
    assert u.acquisition == {"task": "", "devices": {}, "params": {}, "axes": {}}
    assert not any(k.startswith(("Stage", "Pockels", "PMT")) for k, _ in u.info)
