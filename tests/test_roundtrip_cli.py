"""The whole loop, the way someone who is not a programmer would do it:
export a unit, change it with something else, write it back."""
import h5py
import numpy as np
import pytest

from mesc_io import MescFile
from mesc_io.__main__ import main


def test_export_then_writeback_needs_no_one_to_remember_the_units(mesc, tmp_path, capsys):
    out_h5, out_mesc = tmp_path / "u0.h5", tmp_path / "corrected.mesc"
    assert main(["export", str(mesc), "MUnit_0", str(out_h5)]) == 0

    with h5py.File(out_h5, "r+") as f:                      # "process" it elsewhere
        f["data"][...] = np.roll(f["data"][:], 1, axis=1)

    assert main(["writeback", str(mesc), str(out_mesc), "MUnit_0", str(out_h5)]) == 0
    out = capsys.readouterr().out
    assert "says its values are in reader units" in out    # read from the file, not the user
    with MescFile(out_mesc) as f, h5py.File(out_h5, "r") as g:
        assert np.allclose(f.read("MUnit_0"), g["data"][:])
        assert f.unit("MUnit_0").comment.endswith("_MC")


def test_frames_that_do_not_say_their_units_stop_rather_than_guess(mesc, tmp_path, capsys):
    plain = tmp_path / "plain.h5"
    with MescFile(mesc) as f:
        data = f.read("MUnit_0")
    with h5py.File(plain, "w") as h:
        h.create_dataset("data", data=data)                 # no units attribute
    assert main(["writeback", str(mesc), str(tmp_path / "x.mesc"), "MUnit_0", str(plain)]) == 1
    assert "looks right and is not" in capsys.readouterr().err


def test_being_told_the_units_is_enough(mesc, tmp_path):
    plain, out = tmp_path / "plain.h5", tmp_path / "ok.mesc"
    with MescFile(mesc) as f:
        data = f.read("MUnit_0")
    with h5py.File(plain, "w") as h:
        h.create_dataset("data", data=data)
    assert main(["writeback", str(mesc), str(out), "MUnit_0", str(plain),
                 "--reader-units"]) == 0
    assert out.exists()


def test_the_wrong_units_are_refused_at_the_command_line_too(mesc, tmp_path, capsys):
    stored_h5, out = tmp_path / "s.h5", tmp_path / "never.mesc"
    assert main(["export", str(mesc), "MUnit_0", str(stored_h5), "--stored-units"]) == 0
    # claim the stored integers are reader values: the check must catch it
    assert main(["writeback", str(mesc), str(out), "MUnit_0", str(stored_h5),
                 "--reader-units"]) == 1
    assert "refusing to write" in capsys.readouterr().err
    assert not out.exists()


def test_no_tag_leaves_the_comment_alone(mesc, tmp_path):
    h5p, out = tmp_path / "u.h5", tmp_path / "untagged.mesc"
    main(["export", str(mesc), "MUnit_0", str(h5p)])
    main(["writeback", str(mesc), str(out), "MUnit_0", str(h5p), "--no-tag"])
    with MescFile(out) as f:
        assert f.unit("MUnit_0").comment == "first unit"


def test_an_ambiguous_hdf5_asks_which_dataset(mesc, tmp_path, capsys):
    two = tmp_path / "two.h5"
    with MescFile(mesc) as f:
        d = f.read("MUnit_0")
    with h5py.File(two, "w") as h:
        h.create_dataset("a", data=d)
        h.create_dataset("b", data=d)
    assert main(["writeback", str(mesc), str(tmp_path / "x.mesc"), "MUnit_0", str(two)]) == 1
    assert "--dataset" in capsys.readouterr().err
