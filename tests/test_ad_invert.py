"""The PMT A/D inversion flag (``ad_invert`` in MeasurementParamsXML). Reader units are
tested on ad_invert = 1; a channel recorded with 0 must say so instead of reading quietly."""
import warnings

import h5py
import numpy as np
import pytest

from mesc_io import InvertWarning, MescFile
from mesc_io.check import check


def _name(s):
    return np.array([ord(c) for c in s] + [0], dtype=np.int16)


def _xml(inv_ug, inv_ur):
    gear = lambda ch, inv: (f'<Gear name="PMT_{ch}" type="PMT"><param name="reference_voltage" value="70" />'
                            f'<param name="channel_name" value="{ch}" /><param name="ad_invert" value="{inv}" />'
                            f'<param name="ad_offset_16bit" value="0" /></Gear>')
    s = (f'<Task Type="TaskResonantCommon" Version="1.0"><Devices>{gear("UG", inv_ug)}{gear("UR", inv_ur)}'
         '</Devices><Params><param name="objective_name" value="obj16x" /></Params></Task>')
    return np.frombuffer(s.encode("latin-1") + b"\x00" * 64, dtype=np.uint8)


def _file(tmp_path, inv_ug, inv_ur, xml=True):
    path = tmp_path / f"inv_{inv_ug}{inv_ur}{xml}.mesc"
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0/MUnit_0")
        for k, name in enumerate(("UG", "UR")):
            u.create_dataset(f"Channel_{k}", data=np.full((4, 4, 4), 1000, dtype=np.uint16))
            u.attrs[f"Channel_{k}_Name"] = _name(name)
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearOffset"] = -786.0
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearScale"] = 1.0
        if xml:
            u.attrs["MeasurementParamsXML"] = _xml(inv_ug, inv_ur)
        u.attrs["ZAxisConversionConversionLinearScale"] = 16.15
    return path


def test_the_flag_is_read_per_detector(tmp_path):
    with MescFile(_file(tmp_path, 1, 0)) as f:
        assert [c.ad_invert for c in f.unit("MUnit_0").channels] == [1, 0]


def test_no_xml_means_unknown_not_zero(tmp_path):
    with MescFile(_file(tmp_path, 1, 1, xml=False)) as f:
        assert [c.ad_invert for c in f.unit("MUnit_0").channels] == [None, None]
        with warnings.catch_warnings():
            warnings.simplefilter("error", InvertWarning)
            f.read("MUnit_0")


def test_the_tested_case_reads_quietly(tmp_path):
    with MescFile(_file(tmp_path, 1, 1)) as f, warnings.catch_warnings():
        warnings.simplefilter("error", InvertWarning)
        f.read("MUnit_0", channel=1)
        list(f.iter_frames("MUnit_0", channel=1))


def test_an_untested_channel_warns_in_reader_units_only(tmp_path):
    with MescFile(_file(tmp_path, 1, 0)) as f:
        with pytest.warns(InvertWarning, match="ad_invert = 0"):
            f.read("MUnit_0", channel=1)
        with pytest.warns(InvertWarning):
            list(f.iter_frames("MUnit_0", channel=1))
        with warnings.catch_warnings():
            warnings.simplefilter("error", InvertWarning)
            f.read("MUnit_0", channel=1, reader_units=False)   # the stored integers are exact
            f.read("MUnit_0", channel=0)                        # the other detector is fine


def test_check_reports_the_untested_channel(tmp_path):
    rep = check(_file(tmp_path, 1, 0))
    hits = [x for x in rep.findings if x.code == "pmt-not-inverted"]
    assert len(hits) == 1 and hits[0].units == ("MSession_0/MUnit_0/Channel_1",)
    assert not [x for x in check(_file(tmp_path, 1, 1)).findings if x.code == "pmt-not-inverted"]
