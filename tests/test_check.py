from mesc_io.check import check


def _codes(rep):
    return {f.code for f in rep.findings}


def test_a_consistent_file_reports_nothing(mesc):
    rep = check(mesc)
    assert rep.findings == [] and rep.ok and rep.n_units == 2


def test_a_z_stack_beside_the_recordings_is_caught(dirty_mesc):
    rep = check(dirty_mesc)
    assert "mixed-frame-rates" in _codes(rep)
    f = next(f for f in rep.findings if f.code == "mixed-frame-rates")
    assert "1000 Hz" in f.message and f.units == ("MSession_0/MUnit_1",)


def test_a_changed_zoom_is_caught_as_incomparable_distances(dirty_mesc):
    f = next(f for f in check(dirty_mesc).findings if f.code == "mixed-pixel-sizes")
    assert "not comparable" in f.message


def test_a_channel_with_no_conversion_is_named(dirty_mesc):
    f = next(f for f in check(dirty_mesc).findings if f.code == "no-conversion")
    assert f.units == ("MSession_0/MUnit_2/Channel_0",)


def test_a_conversion_that_differs_between_units_is_caught(dirty_mesc):
    assert "mixed-conversion" in _codes(check(dirty_mesc))


def test_an_aborted_recording_is_noted_not_warned(dirty_mesc):
    f = next(f for f in check(dirty_mesc).findings if f.code == "not-a-movie")
    assert f.level == "note" and f.units == ("MSession_0/MUnit_2",)


def test_a_dirty_file_is_not_ok_and_says_so_in_one_line(dirty_mesc):
    rep = check(dirty_mesc)
    assert not rep.ok
    assert "3 unit(s)" in str(rep) and "warn" in str(rep)
