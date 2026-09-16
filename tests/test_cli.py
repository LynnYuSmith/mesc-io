import pytest

from mesc_io.__main__ import main


def test_info_lists_every_unit_with_its_rate(mesc, capsys):
    assert main(["info", str(mesc)]) == 0
    out = capsys.readouterr().out
    assert "2 unit(s)" in out and "MSession_0/MUnit_0" in out and "61.909 Hz" in out


def test_info_says_unknown_rather_than_inventing_a_rate(mesc_without_rate, capsys):
    assert main(["info", str(mesc_without_rate)]) == 0
    assert "unknown" in capsys.readouterr().out


def test_export_picks_the_writer_from_the_output_suffix(mesc, tmp_path, capsys):
    out = tmp_path / "u.h5"
    assert main(["export", str(mesc), "MUnit_1", str(out)]) == 0
    assert out.exists() and "reader units" in capsys.readouterr().out


def test_a_missing_file_fails_with_a_message_not_a_traceback(tmp_path, capsys):
    assert main(["info", str(tmp_path / "nope.mesc")]) == 1
    assert "FileNotFoundError" in capsys.readouterr().err


def test_an_unknown_unit_fails_cleanly(mesc, tmp_path, capsys):
    assert main(["export", str(mesc), "MUnit_99", str(tmp_path / "x.h5")]) == 1
    assert "MUnit_99" in capsys.readouterr().err
