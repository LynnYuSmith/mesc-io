import json

import pytest

from mesc_io.presets import (PresetError, delete_preset, list_presets, load_preset, preset_dir,
                             save_preset)


@pytest.fixture(autouse=True)
def _own_dir(tmp_path, monkeypatch):
    """Every test gets its own preset directory; the real ~/.config is never touched."""
    monkeypatch.setenv("MESC_IO_PRESETS", str(tmp_path / "presets"))


def test_a_saved_preset_comes_back_as_it_was_saved():
    path = save_preset("soma", {"block_size": 128, "max_shift_nr": 5, "ops": {"smooth_sigma": 2.0}},
                       "coarser blocks for soma fields")
    assert path == preset_dir() / "soma.json"
    got = load_preset("soma")
    assert got["settings"] == {"block_size": 128, "max_shift_nr": 5.0, "ops": {"smooth_sigma": 2.0}}
    assert got["description"] == "coarser blocks for soma fields" and got["source"] == str(path)
    assert json.loads(path.read_text())["mesc_io_preset"] == 1


def test_a_preset_file_can_be_read_from_anywhere(tmp_path):
    save_preset("mine", {"nonrigid": False})
    shared = tmp_path / "for_a_colleague.json"
    shared.write_text((preset_dir() / "mine.json").read_text())
    assert load_preset(str(shared))["settings"] == {"nonrigid": False}


def test_a_preset_holds_settings_and_never_which_units_share_a_reference():
    with pytest.raises(PresetError, match="named per run"):
        save_preset("grouped", {"groups": [["MUnit_0", "MUnit_1"]]})
    with pytest.raises(PresetError, match="must be bool"):
        save_preset("typo", {"nonrigid": "yes"})
    with pytest.raises(PresetError, match="block EDGE"):
        save_preset("tiny", {"block_size": 2})


def test_the_builtin_cannot_be_overwritten_or_deleted_and_a_name_is_not_clobbered():
    with pytest.raises(PresetError, match="built in"):
        save_preset("pipeline", {})
    with pytest.raises(PresetError, match="built in"):
        delete_preset("pipeline")
    save_preset("a", {"block_size": 32})
    with pytest.raises(PresetError, match="already exists"):
        save_preset("a", {"block_size": 64})
    save_preset("a", {"block_size": 64}, overwrite=True)
    assert load_preset("a")["settings"]["block_size"] == 64
    with pytest.raises(PresetError, match="not a preset name"):
        save_preset("../escape", {})


def test_list_shows_the_builtin_the_saved_and_an_unreadable_one_as_such():
    save_preset("b", {})
    (preset_dir() / "broken.json").write_text("{ not json")
    got = {p["name"]: p for p in list_presets()}
    assert got["pipeline"]["source"] == "built in" and "b" in got
    assert got["broken"]["description"].startswith("UNREADABLE")
    delete_preset("b")
    assert "b" not in {p["name"] for p in list_presets()}


def test_an_unknown_name_says_what_there_is():
    with pytest.raises(PresetError, match="Have: pipeline"):
        load_preset("nope")


def test_the_cli_saves_lists_and_shows(capsys):
    from mesc_io.__main__ import main
    assert main(["preset", "save", "wide", "--block-size", "96", "--rigid",
                 "--description", "a test"]) == 0
    assert load_preset("wide")["settings"] == {"nonrigid": False, "block_size": 96}
    assert main(["preset", "list"]) == 0
    assert "wide" in capsys.readouterr().out
    assert main(["preset", "save", "wide"]) == 1          # exists: refused, not clobbered
    assert main(["preset", "delete", "wide"]) == 0


def test_an_explicit_argument_beats_the_preset_which_beats_the_default(moving_mesc, tmp_path):
    pytest.importorskip("suite2p", reason="registration is an optional extra")
    from mesc_io.registration import register_file
    path, _, _ = moving_mesc
    save_preset("loose", {"max_shift_nr": 5.0, "block_size": 32, "ops": {"smooth_sigma": 1.5}})
    rep = register_file(path, tmp_path / "a.mesc", preset="loose", block_size=48)
    assert rep["settings"] == {"nonrigid": True, "block_size": 48, "max_shift": 0.1,
                               "max_shift_nr": 5.0}          # arg > preset > default
    assert rep["ops"] == {"smooth_sigma": 1.5}
    assert rep["preset"]["name"] == "loose" and rep["preset"]["source"].endswith("loose.json")
    rep = register_file(path, tmp_path / "b.mesc", preset="loose", ops={"smooth_sigma": 3.0})
    assert rep["ops"] == {"smooth_sigma": 3.0}                 # the run's ops win


def test_a_preset_with_a_misspelled_suite2p_option_is_refused_at_save():
    pytest.importorskip("suite2p", reason="the option list comes from suite2p")
    with pytest.raises(PresetError, match="no such option"):
        save_preset("oops", {"ops": {"smooth_sigmaa": 2.0}})
