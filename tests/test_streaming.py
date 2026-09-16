import numpy as np
import pytest

from mesc_io import MescFile


def test_streaming_covers_the_whole_recording_in_blocks(mesc):
    with MescFile(mesc) as f:
        blocks = list(f.iter_frames("MUnit_0", block=5))
        assert [b.shape[0] for b in blocks] == [5, 5, 2]
        assert np.allclose(np.concatenate(blocks), f.read("MUnit_0"))


def test_streaming_and_reading_agree_in_stored_units_too(mesc):
    with MescFile(mesc) as f:
        streamed = np.concatenate(list(f.iter_frames("MUnit_0", block=4, reader_units=False)))
        assert np.array_equal(streamed, f.read("MUnit_0", reader_units=False))


def test_a_zero_block_is_refused_rather_than_looping_forever(mesc):
    with MescFile(mesc) as f:
        with pytest.raises(ValueError):
            next(f.iter_frames("MUnit_0", block=0))


def test_a_read_that_would_not_fit_is_refused_with_the_way_out(mesc):
    with MescFile(mesc) as f:
        with pytest.raises(MemoryError, match="iter_frames"):
            f.read("MUnit_0", max_gb=1e-9)


def test_the_guard_counts_only_the_frames_asked_for(mesc):
    with MescFile(mesc) as f:
        # the whole unit trips a guard that one frame passes
        with pytest.raises(MemoryError):
            f.read("MUnit_0", max_gb=1.4e-6)
        assert f.read("MUnit_0", frames=slice(0, 1), max_gb=1.4e-6).shape[0] == 1


def test_the_guard_can_be_lifted_deliberately(mesc):
    with MescFile(mesc) as f:
        assert f.read("MUnit_0", max_gb=None).shape == (12, 4, 4)
