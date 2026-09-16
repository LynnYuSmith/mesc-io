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


def test_info_json_is_parseable_and_carries_the_numbers(mesc, capsys):
    import json
    assert main(["info", str(mesc), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["unit"] for r in rows] == ["MSession_0/MUnit_0", "MSession_0/MUnit_1"]
    assert rows[0]["frame_rate_hz"] == pytest.approx(61.909, abs=1e-3)
    assert rows[0]["channels"][1]["offset"] == -1170.0


def test_info_json_says_null_where_the_file_says_nothing(mesc_without_rate, capsys):
    import json
    main(["info", str(mesc_without_rate), "--json"])
    assert json.loads(capsys.readouterr().out)[0]["frame_rate_hz"] is None


def test_check_json_carries_the_findings(dirty_mesc, capsys):
    import json
    assert main(["check", str(dirty_mesc), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["ok"] is False and rep["units"] == 3
    assert "mixed-frame-rates" in {f["code"] for f in rep["findings"]}


def test_check_json_on_a_clean_file_is_ok_and_empty(mesc, capsys):
    import json
    main(["check", str(mesc), "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert rep["ok"] is True and rep["findings"] == []
