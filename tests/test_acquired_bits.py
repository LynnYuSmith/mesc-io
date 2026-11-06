"""8-bit acquisition (``Params/BitCompression = 8``): uint16 containers holding 8-bit samples
shifted up by ``compression_shift_8bit``. Not an error, but worth knowing before an offset or
an SNR is read off a single frame."""
import h5py
import numpy as np

from mesc_io import MescFile
from mesc_io.check import check


def _xml(bits):
    gear = lambda ch: (f'<Gear name="PMT_{ch}" type="PMT"><param name="channel_name" value="{ch}" />'
                       '<param name="ad_invert" value="1" /><param name="compression_shift_16bit" value="0" />'
                       '<param name="compression_shift_8bit" value="7" /></Gear>')
    params = "" if bits is None else f'<param name="BitCompression" value="{bits}" />'
    s = (f'<Task Type="TaskResonantCommon" Version="1.0"><Devices>{gear("UG")}</Devices>'
         f'<Params><param name="NiClock" value="5e7" />{params}</Params></Task>')
    return np.frombuffer(s.encode("latin-1") + b"\x00", dtype=np.uint8)


def _file(tmp_path, bits_per_unit):
    path = tmp_path / "bits.mesc"
    with h5py.File(path, "w") as f:
        for j, bits in enumerate(bits_per_unit):
            u = f.create_group(f"MSession_0/MUnit_{j}")
            u.create_dataset("Channel_0", data=(np.arange(64, dtype=np.uint16).reshape(4, 4, 4) % 30) << 7)
            u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = -786.0
            u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
            u.attrs["ZAxisConversionConversionLinearScale"] = 16.15
            if bits != "no-xml":
                u.attrs["MeasurementParamsXML"] = _xml(bits)
    return path


def test_the_mode_and_its_shift_are_read(tmp_path):
    with MescFile(_file(tmp_path, [8, 16, None, "no-xml"])) as f:
        got = [(u.acquired_bits, u.sample_shift) for u in f.units()]
    assert got == [(8, 7), (16, 0), (None, None), (None, None)]


def test_check_notes_the_8_bit_units_only(tmp_path):
    rep = check(_file(tmp_path, [8, 16]))
    hits = [x for x in rep.findings if x.code == "8-bit-acquisition"]
    assert len(hits) == 1 and hits[0].level == "note"
    assert hits[0].units == ("MSession_0/MUnit_0",) and "<< 7" in hits[0].message
    assert not [x for x in check(_file(tmp_path, [16])).findings if x.code == "8-bit-acquisition"]
