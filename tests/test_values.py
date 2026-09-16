import numpy as np
import pytest

from mesc_io import from_reader_units, to_reader_units
from mesc_io.values import ConversionError


def test_the_offset_is_what_the_reader_removes():
    stored = np.array([786, 1000, 2000], dtype=np.uint16)
    assert to_reader_units(stored, offset=-786.0).tolist() == [0.0, 214.0, 1214.0]


def test_negatives_are_kept_not_clipped():
    # a pixel below the PMT floor is information about the file, not something to hide
    assert to_reader_units(np.array([0], dtype=np.uint16), offset=-786.0)[0] == -786.0


def test_round_trip_is_exact():
    stored = np.array([0, 1, 786, 4095, 65535], dtype=np.uint16)
    back = from_reader_units(to_reader_units(stored, offset=-786.0), offset=-786.0)
    assert np.array_equal(back, stored)


def test_halved_arrays_are_restored_before_the_offset():
    # int16 registration halves the data; the offset belongs to the raw integers
    raw = np.array([2000], dtype=np.uint16)
    halved = ((raw.astype(np.int32) - 786) // 2).astype(np.int16)
    assert to_reader_units(halved, offset=0.0, halved=True)[0] == 1214.0


def test_writing_back_clips_to_the_target_range():
    out = from_reader_units(np.array([1e9, -1e9]), offset=-786.0)
    assert out.tolist() == [65535, 0]


def test_a_zero_scale_is_refused_rather_than_dividing_by_it():
    with pytest.raises(ConversionError):
        from_reader_units(np.array([1.0]), offset=0.0, scale=0.0)
