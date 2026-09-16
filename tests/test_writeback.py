import h5py
import numpy as np
import pytest

from mesc_io import MescFile
from mesc_io.writeback import WritebackError, write_frames


def _shifted(mesc, unit="MUnit_0", channel=0, by=1):
    """The unit's own frames, rolled — a stand-in for registration, same units, same content."""
    with MescFile(mesc) as f:
        return np.roll(f.read(unit, channel=channel), by, axis=1)


def test_the_source_is_never_modified(mesc, tmp_path):
    before = mesc.read_bytes()
    write_frames(mesc, tmp_path / "out.mesc", {"MUnit_0": {"Channel_0": _shifted(mesc)}})
    assert mesc.read_bytes() == before


def test_the_frames_come_back_as_written(mesc, tmp_path):
    new = _shifted(mesc)
    out = tmp_path / "out.mesc"
    write_frames(mesc, out, {"MUnit_0": {"Channel_0": new}})
    with MescFile(out) as f:
        assert np.allclose(f.read("MUnit_0", channel=0), new)


def test_untouched_units_and_channels_are_left_alone(mesc, tmp_path):
    out = tmp_path / "out.mesc"
    write_frames(mesc, out, {"MUnit_0": {"Channel_0": _shifted(mesc)}})
    with MescFile(mesc) as a, MescFile(out) as b:
        assert np.array_equal(a.read("MUnit_1", reader_units=False),
                              b.read("MUnit_1", reader_units=False))
        assert np.array_equal(a.read("MUnit_0", channel=1, reader_units=False),
                              b.read("MUnit_0", channel=1, reader_units=False))


def test_the_written_unit_is_tagged_so_it_cannot_pass_for_the_original(mesc, tmp_path):
    out = tmp_path / "out.mesc"
    write_frames(mesc, out, {"MUnit_0": {"Channel_0": _shifted(mesc)}})
    with MescFile(out) as f:
        assert f.unit("MUnit_0").comment.endswith("_MC")
        assert not f.unit("MUnit_1").comment.endswith("_MC")


def test_tagging_twice_does_not_stack_the_tag(mesc, tmp_path):
    a, b = tmp_path / "a.mesc", tmp_path / "b.mesc"
    write_frames(mesc, a, {"MUnit_0": {"Channel_0": _shifted(mesc)}})
    write_frames(a, b, {"MUnit_0": {"Channel_0": _shifted(a)}})
    with MescFile(b) as f:
        assert f.unit("MUnit_0").comment.count("_MC") == 1


def test_wrong_units_are_refused_instead_of_written(mesc, tmp_path):
    # the classic mistake: handing over stored integers while saying they are reader values
    with MescFile(mesc) as f:
        stored = f.read("MUnit_0", channel=0, reader_units=False).astype(np.float64)
    with pytest.raises(WritebackError, match="units you think"):
        write_frames(mesc, tmp_path / "bad.mesc", {"MUnit_0": {"Channel_0": stored}})


def test_a_refusal_leaves_no_output_behind(mesc, tmp_path):
    out = tmp_path / "never.mesc"
    with MescFile(mesc) as f:
        stored = f.read("MUnit_0", channel=0, reader_units=False).astype(np.float64)
    with pytest.raises(WritebackError):
        write_frames(mesc, out, {"MUnit_0": {"Channel_0": stored}})
    assert not out.exists()


def test_shorter_frames_are_aligned_to_the_end_and_said_so(mesc, tmp_path):
    new = _shifted(mesc)[3:]
    out = tmp_path / "short.mesc"
    rep = write_frames(mesc, out, {"MUnit_0": {"Channel_0": new}})
    assert any("aligned to the end" in w for w in rep["warnings"])
    with MescFile(out) as a, MescFile(mesc) as b:
        # the first three frames are still the originals
        assert np.array_equal(a.read("MUnit_0", frames=slice(0, 3), reader_units=False),
                              b.read("MUnit_0", frames=slice(0, 3), reader_units=False))
        assert np.allclose(a.read("MUnit_0", frames=slice(3, None)), new)


def test_more_frames_than_the_file_holds_is_refused(mesc, tmp_path):
    new = np.concatenate([_shifted(mesc)] * 2)
    with pytest.raises(WritebackError, match="holds only"):
        write_frames(mesc, tmp_path / "long.mesc", {"MUnit_0": {"Channel_0": new}})


def test_a_different_frame_size_is_refused(mesc, tmp_path):
    with pytest.raises(WritebackError, match="frame size must match"):
        write_frames(mesc, tmp_path / "x.mesc",
                     {"MUnit_0": {"Channel_0": np.zeros((12, 8, 8))}})


def test_an_unknown_unit_or_channel_is_named(mesc, tmp_path):
    with pytest.raises(WritebackError, match="MUnit_9"):
        write_frames(mesc, tmp_path / "x.mesc", {"MUnit_9": {"Channel_0": _shifted(mesc)}})
    with pytest.raises(WritebackError, match="Channel_7"):
        write_frames(mesc, tmp_path / "x.mesc", {"MUnit_0": {"Channel_7": _shifted(mesc)}})
