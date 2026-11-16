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


# --- 0.6.7 ---------------------------------------------------------------------------------------

def _two_units(path, convs, sizes):
    import h5py
    import numpy as np
    with h5py.File(path, "w") as f:
        s = f.create_group("MSession_0")
        for i, (conv, px) in enumerate(zip(convs, sizes)):
            u = s.create_group(f"MUnit_{i}")
            u.create_dataset("Channel_0", data=np.zeros((5, 2, 2), np.uint16))
            u.attrs["ZAxisConversionConversionLinearScale"] = 16.0
            u.attrs["XAxisConversionConversionLinearScale"] = px
            if conv is not None:
                u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = conv[0]
                u.attrs["Channel_0_Conversion_ConversionLinearScale"] = conv[1]
    return path


def test_a_stated_identity_conversion_is_a_conversion(tmp_path):
    p = _two_units(tmp_path / "a.mesc", [(0.0, 1.0), None], [0.5, 0.5])
    found = [f for f in check(p).findings if f.code == "no-conversion"]
    assert len(found) == 1 and found[0].units == ("MSession_0/MUnit_1/Channel_0",)


def test_pixel_sizes_equal_to_six_figures_are_one_size(tmp_path):
    p = _two_units(tmp_path / "b.mesc", [(-786.0, 1.0)] * 2, [0.44911766052246094, 0.4491177])
    assert "mixed-pixel-sizes" not in [f.code for f in check(p).findings]
    q = _two_units(tmp_path / "c.mesc", [(-786.0, 1.0)] * 2, [0.449, 0.5])     # the control
    assert "mixed-pixel-sizes" in [f.code for f in check(q).findings]
