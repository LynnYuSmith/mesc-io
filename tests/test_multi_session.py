"""A file with more than one session must never hand back the wrong recording quietly."""
import numpy as np
import pytest

from mesc_io import MescError, MescFile
from mesc_io.writeback import WritebackError, write_frames


def test_every_session_is_seen(two_session_mesc):
    with MescFile(two_session_mesc) as f:
        assert f.sessions() == ["MSession_0", "MSession_1"]
        assert [u.path for u in f.units()] == [
            "MSession_0/MUnit_0", "MSession_0/MUnit_1",
            "MSession_1/MUnit_0", "MSession_1/MUnit_1"]


def test_an_ambiguous_short_name_is_refused_not_resolved_to_the_first(two_session_mesc):
    with MescFile(two_session_mesc) as f:
        with pytest.raises(MescError, match="ambiguous"):
            f.unit("MUnit_0")


def test_the_full_path_always_works(two_session_mesc):
    with MescFile(two_session_mesc) as f:
        got = f.read("MSession_1/MUnit_0", frames=slice(0, 1), reader_units=False)
        assert int(got.flat[0]) == 1100        # the second session's value, not the first's


def test_writeback_reaches_a_unit_outside_the_first_session(two_session_mesc, tmp_path):
    out = tmp_path / "out.mesc"
    with MescFile(two_session_mesc) as f:
        new = f.read("MSession_1/MUnit_1")
    write_frames(two_session_mesc, out, {"MSession_1/MUnit_1": {"Channel_0": new + 1.0}})
    with MescFile(out) as f:
        assert int(f.read("MSession_1/MUnit_1", frames=slice(0, 1),
                          reader_units=False).flat[0]) == 1102
        # and nothing else moved
        assert int(f.read("MSession_0/MUnit_1", frames=slice(0, 1),
                          reader_units=False).flat[0]) == 1001


def test_writeback_refuses_an_ambiguous_name_too(two_session_mesc, tmp_path):
    with MescFile(two_session_mesc) as f:
        new = f.read("MSession_0/MUnit_0")
    with pytest.raises(WritebackError, match="ambiguous"):
        write_frames(two_session_mesc, tmp_path / "x.mesc", {"MUnit_0": {"Channel_0": new}})


def test_a_bare_name_that_is_unique_still_works(mesc, tmp_path):
    with MescFile(mesc) as f:
        new = f.read("MUnit_0")
    rep = write_frames(mesc, tmp_path / "ok.mesc", {"MUnit_0": {"Channel_0": new}})
    assert rep["written"] == ["MSession_0/MUnit_0/Channel_0"]
