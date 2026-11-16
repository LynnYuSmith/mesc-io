import h5py
import numpy as np
import pytest

from mesc_io import MescFile
from mesc_io.export import to_hdf5


def test_hdf5_export_carries_the_metadata_the_mesc_had(mesc, tmp_path):
    with MescFile(mesc) as f:
        out = to_hdf5(f, "MUnit_0", tmp_path / "u0.h5")
    with h5py.File(out, "r") as h:
        ds = h["data"]
        assert ds.shape == (12, 4, 4)
        assert ds.attrs["units"] == "reader"
        assert ds.attrs["conversion_offset"] == -786.0
        assert ds.attrs["frame_rate_hz"] == pytest.approx(61.909, abs=1e-3)
        assert ds.attrs["pixel_size_um"] == pytest.approx(0.439453125)
        assert ds.attrs["source_unit"] == "MSession_0/MUnit_0"


def test_reader_units_are_written_as_float_so_negatives_survive(mesc, tmp_path):
    with MescFile(mesc) as f:
        out = to_hdf5(f, "MUnit_0", tmp_path / "f.h5")
    with h5py.File(out, "r") as h:
        assert h["data"].dtype == np.float32


def test_stored_units_keep_the_files_own_integer_type(mesc, tmp_path):
    with MescFile(mesc) as f:
        out = to_hdf5(f, "MUnit_0", tmp_path / "s.h5", reader_units=False)
    with h5py.File(out, "r") as h:
        assert h["data"].dtype == np.uint16
        assert h["data"].attrs["units"] == "stored"


def test_a_frame_selection_is_honoured(mesc, tmp_path):
    with MescFile(mesc) as f:
        out = to_hdf5(f, "MUnit_0", tmp_path / "part.h5", frames=slice(0, 3))
    with h5py.File(out, "r") as h:
        assert h["data"].shape[0] == 3


def test_a_z_stack_keeps_its_slice_step_in_hdf5(tmp_path):
    import h5py
    import numpy as np
    from mesc_io import MescFile
    from mesc_io.export import to_hdf5
    p = tmp_path / "stack.mesc"
    with h5py.File(p, "w") as f:
        u = f.create_group("MSession_0").create_group("MUnit_0")
        u.create_dataset("Channel_0", data=np.zeros((6, 3, 4), np.uint16))
        u.attrs["ZAxisConversionConversionLinearScale"] = 2.5
        u.attrs["ZAxisGeomRole"] = 3.0
        u.attrs["XAxisConversionConversionLinearScale"] = 0.5
        u.attrs["YAxisConversionConversionLinearScale"] = 0.6
    with MescFile(p) as m:
        out = to_hdf5(m, "MUnit_0", tmp_path / "s.h5")
    with h5py.File(out, "r") as f:
        a = f["data"].attrs
        assert a["axes"] == "ZYX" and a["z_step_um"] == 2.5 and "frame_rate_hz" not in a
        assert a["pixel_size_um"] == 0.5 and a["pixel_size_y_um"] == 0.6
