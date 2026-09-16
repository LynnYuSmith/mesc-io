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
