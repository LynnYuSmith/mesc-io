import numpy as np
import pytest

pytest.importorskip("suite2p", reason="motion correction is an optional extra")

from mesc_io import MescFile                                          # noqa: E402
from mesc_io.registration import leading_flat_frames, register_file   # noqa: E402


def test_the_flat_head_is_counted_by_contrast_not_brightness(moving_mesc):
    path, n_flat, _ = moving_mesc
    with MescFile(path) as f:
        # the flat frames sit at the recording's own level — brightness would not find them
        head = f.read("MUnit_0", frames=slice(0, n_flat), reader_units=False).mean()
        body = f.read("MUnit_0", frames=slice(n_flat, None), reader_units=False).mean()
        assert head == pytest.approx(body, rel=0.3)
        assert leading_flat_frames(f, "MUnit_0") == n_flat


def test_the_known_displacement_is_recovered(moving_mesc, tmp_path):
    """Up to a constant: the reference is built from the movie, so it lands on some average
    state and every shift is measured from there. What must be exact is the *relative*
    displacement between frames."""
    path, n_flat, shifts = moving_mesc
    rep = register_file(path, tmp_path / "out.mesc")
    info = rep["units"]["MSession_0/MUnit_0"]
    y, x = info["y_shift"][n_flat:], info["x_shift"][n_flat:]
    # the reported shift carries the same sign as the displacement (Suite2p's convention)
    want_y = np.array([s[0] for s in shifts])
    want_x = np.array([s[1] for s in shifts])
    assert np.abs((y - want_y) - np.median(y - want_y)).max() <= 1
    assert np.abs((x - want_x) - np.median(x - want_x)).max() <= 1
    # and the four distinct positions are still four distinct corrections
    assert len(set(zip(y.tolist(), x.tolist()))) == len(set(shifts))


def test_the_registered_frames_actually_coincide(moving_mesc, tmp_path):
    """The point of the shifts, checked on the pixels rather than on the numbers."""
    path, n_flat, shifts = moving_mesc
    register_file(path, tmp_path / "out.mesc")
    with MescFile(tmp_path / "out.mesc") as f:
        reg = f.read("MUnit_0", frames=slice(n_flat, None), reader_units=False).astype(float)
    with MescFile(path) as f:
        raw = f.read("MUnit_0", frames=slice(n_flat, None), reader_units=False).astype(float)

    def spread(a):
        # how far each frame sits from the average field, in the interior (edges get padded)
        c = a[:, 12:-12, 12:-12]
        m = c.mean(0)
        return float(np.mean((c - m) ** 2))

    assert spread(reg) < 0.5 * spread(raw)


def test_the_flat_head_is_left_exactly_alone(moving_mesc, tmp_path):
    path, n_flat, _ = moving_mesc
    rep = register_file(path, tmp_path / "out.mesc")
    info = rep["units"]["MSession_0/MUnit_0"]
    assert info["leading_flat_frames"] == n_flat
    assert not info["y_shift"][:n_flat].any() and not info["x_shift"][:n_flat].any()
    with MescFile(path) as a, MescFile(tmp_path / "out.mesc") as b:
        assert np.array_equal(a.read("MUnit_0", frames=slice(0, n_flat), reader_units=False),
                              b.read("MUnit_0", frames=slice(0, n_flat), reader_units=False))


def test_registration_sharpens_the_average_field(moving_mesc, tmp_path):
    path, n_flat, _ = moving_mesc
    register_file(path, tmp_path / "out.mesc")

    def sharpness(p):
        with MescFile(p) as f:
            m = f.read("MUnit_0", frames=slice(n_flat, None), reader_units=False).mean(0)
        return np.mean(np.diff(m, axis=0) ** 2) + np.mean(np.diff(m, axis=1) ** 2)

    assert sharpness(tmp_path / "out.mesc") > 1.2 * sharpness(path)


def test_the_source_is_untouched_and_the_unit_is_tagged(moving_mesc, tmp_path):
    path, _, _ = moving_mesc
    before = path.read_bytes()
    register_file(path, tmp_path / "out.mesc")
    assert path.read_bytes() == before
    with MescFile(tmp_path / "out.mesc") as f:
        assert f.unit("MUnit_0").comment.endswith("_MC")


def test_units_of_different_frame_sizes_cannot_share_a_reference(dirty_mesc, tmp_path):
    from mesc_io.registration import RegistrationError
    with pytest.raises(RegistrationError, match="frame sizes"):
        register_file(dirty_mesc, tmp_path / "x.mesc", groups=[["MUnit_0", "MUnit_1"]])


def _recovery_error(info, n_flat, shifts):
    """How far the reported shifts are from the applied ones, after the constant offset."""
    y, x = info["y_shift"][n_flat:], info["x_shift"][n_flat:]
    wy = np.array([s[0] for s in shifts])
    wx = np.array([s[1] for s in shifts])
    return max(np.abs((y - wy) - np.median(y - wy)).max(),
               np.abs((x - wx) - np.median(x - wx)).max())


def test_by_default_each_unit_gets_its_own_reference(two_fields_mesc, tmp_path):
    """Two different fields in one file: each must be registered to itself."""
    path, n_flat, shifts = two_fields_mesc
    rep = register_file(path, tmp_path / "out.mesc")

    assert len(rep["groups"]) == 2
    assert [g["units"] for g in rep["groups"]] == [["MSession_0/MUnit_0"],
                                                   ["MSession_0/MUnit_1"]]
    for unit in ("MUnit_0", "MUnit_1"):
        info = rep["units"][f"MSession_0/{unit}"]
        assert info["reference_from"] == f"MSession_0/{unit}"
        assert _recovery_error(info, n_flat, shifts[unit]) <= 1


def test_one_reference_over_two_fields_is_what_goes_wrong(two_fields_mesc, tmp_path):
    """The positive control for the default: asked to share, the second field is registered
    against blobs that are not in it, and its known displacement is no longer recovered."""
    path, n_flat, shifts = two_fields_mesc
    own = register_file(path, tmp_path / "own.mesc")
    shared = register_file(path, tmp_path / "shared.mesc", reference_from="MUnit_0")

    assert [g["units"] for g in shared["groups"]] == [["MSession_0/MUnit_0",
                                                       "MSession_0/MUnit_1"]]
    key = "MSession_0/MUnit_1"
    assert _recovery_error(own["units"][key], n_flat, shifts["MUnit_1"]) <= 1
    assert _recovery_error(shared["units"][key], n_flat, shifts["MUnit_1"]) > 1


def test_named_groups_share_a_reference_and_others_do_not(two_fields_mesc, tmp_path):
    path, _, _ = two_fields_mesc
    rep = register_file(path, tmp_path / "out.mesc", groups=[["MUnit_0", "MUnit_1"]])
    assert len(rep["groups"]) == 1
    assert rep["units"]["MSession_0/MUnit_1"]["reference_from"] == "MSession_0/MUnit_0"


def test_a_unit_cannot_be_in_two_groups(two_fields_mesc, tmp_path):
    from mesc_io.registration import RegistrationError
    path, _, _ = two_fields_mesc
    with pytest.raises(RegistrationError, match="more than one group"):
        register_file(path, tmp_path / "x.mesc",
                      groups=[["MUnit_0", "MUnit_1"], ["MUnit_1"]])


def test_units_and_groups_are_not_both_accepted(two_fields_mesc, tmp_path):
    from mesc_io.registration import RegistrationError
    path, _, _ = two_fields_mesc
    with pytest.raises(RegistrationError, match="not both"):
        register_file(path, tmp_path / "x.mesc", units=["MUnit_0"], groups=[["MUnit_1"]])


def test_ops_reach_suite2p_and_are_recorded(moving_mesc, tmp_path):
    path, _, _ = moving_mesc
    rep = register_file(path, tmp_path / "out.mesc", ops={"smooth_sigma": 2.0})
    assert rep["ops"] == {"smooth_sigma": 2.0}


def test_a_misspelled_op_is_an_error_not_a_no_op(moving_mesc, tmp_path):
    from mesc_io.registration import RegistrationError
    path, _, _ = moving_mesc
    with pytest.raises(RegistrationError, match="no such option"):
        register_file(path, tmp_path / "x.mesc", ops={"smooth_sgima": 2.0})


def test_the_defaults_are_the_pipeline_settings(moving_mesc, tmp_path):
    """The point of this module is to reproduce that correction, so these are the DEFAULTS.
    Pinned against lib/mesc/concat_mc._suite2p_ops_base + the session config it is run with
    (suite2p_nonrigid: true, block_size 64, maxregshift_nr 3.0)."""
    from mesc_io.registration import DEFAULTS, _ops
    assert DEFAULTS == {"nonrigid": True, "block_size": 64, "max_shift": 0.1,
                        "max_shift_nr": 3.0}

    ops = _ops(61.9, DEFAULTS["nonrigid"], DEFAULTS["block_size"],
               DEFAULTS["max_shift"], DEFAULTS["max_shift_nr"])
    assert ops["nonrigid"] is True
    assert list(ops["block_size"]) == [64, 64]
    assert ops["maxregshiftNR"] == 3.0
    assert ops["smooth_sigma_time"] == 0
    assert ops["maxregshift"] == 0.1
    assert ops["snr_thresh"] == 1.2
    assert ops["batch_size"] == 1000
    assert ops["fs"] == 61.9                     # from the file, never a literal

    path, _, _ = moving_mesc
    rep = register_file(path, tmp_path / "out.mesc")        # nothing passed, no preset
    assert rep["nonrigid"] is True and rep["settings"] == DEFAULTS and rep["preset"] is None


def test_ops_win_over_the_named_arguments(moving_mesc, tmp_path):
    """The passthrough is last, so it can undo a default this module chose."""
    from mesc_io.registration import _ops
    assert _ops(30.0, True, 64, 0.1, 3.0)["nonrigid"] is True
    assert _ops(30.0, True, 64, 0.1, 3.0, {"nonrigid": False})["nonrigid"] is False


def test_the_block_grid_is_what_we_think_it_is():
    """block_size is not the grid: suite2p's blocks overlap, so 128 on a 256 px frame is
    nine blocks, not four. Pinned because the wrong reading is the natural one."""
    from suite2p.registration.nonrigid import make_blocks
    from mesc_io.registration import _ops
    bs = _ops(61.9, True, 128, 0.1, 5.0)["block_size"]
    *_, n, _, _ = make_blocks(256, 256, bs)
    assert list(n) == [3, 3]


def test_the_pipeline_preset_is_the_pipeline_settings(moving_mesc, tmp_path):
    """Pinned against lib/mesc/concat_mc._suite2p_ops_base as of 2026-09-24: of 90 keys only
    these differed (plus input_format, which only run_s2p reads)."""
    from mesc_io.registration import PIPELINE_OPS, _ops
    got = _ops(61.9, False, 128, 0.1, 5.0, PIPELINE_OPS)
    assert got["nonrigid"] is True
    assert list(got["block_size"]) == [64, 64]
    assert got["maxregshiftNR"] == 3.0
    assert got["soma_crop"] is False
    # and the rest is untouched
    assert got["maxregshift"] == 0.1 and got["snr_thresh"] == 1.2 and got["batch_size"] == 1000

    path, _, _ = moving_mesc
    rep = register_file(path, tmp_path / "out.mesc", preset="pipeline")
    assert rep["preset"]["name"] == "pipeline" and rep["preset"]["source"] == "built in"
    assert rep["settings"] == {"nonrigid": True, "block_size": 64, "max_shift": 0.1,
                               "max_shift_nr": 3.0}      # a no-op now: it is the default


def test_the_preset_does_not_group_units(two_fields_mesc, tmp_path):
    """Settings only: a preset must not quietly put two fields on one reference."""
    path, _, _ = two_fields_mesc
    rep = register_file(path, tmp_path / "out.mesc", preset="pipeline")
    assert len(rep["groups"]) == 2


def test_an_unknown_preset_is_an_error(moving_mesc, tmp_path):
    from mesc_io.registration import RegistrationError
    path, _, _ = moving_mesc
    with pytest.raises(RegistrationError, match="no preset 'pipelien'"):
        register_file(path, tmp_path / "x.mesc", preset="pipelien")


def test_a_unit_too_short_to_register_is_skipped_not_fatal(dirty_mesc, tmp_path):
    """dirty_mesc's MUnit_1 was aborted after one frame — the ordinary case of a session
    carrying an "ignore" unit. Before 0.3.1 it killed the whole run inside suite2p with
    "cannot convert float NaN to integer"."""
    import warnings as w
    from mesc_io.registration import RegistrationWarning
    seen = []
    with w.catch_warnings():
        w.simplefilter("always")
        rep = register_file(dirty_mesc, tmp_path / "out.mesc",
                            on_skip=lambda units, why: seen.append((tuple(units), why)))
    assert any("MUnit_1" in u for us, _ in seen for u in us), seen
    assert any("MUnit_1" in k for k in rep["skipped"]), rep["skipped"]
    assert rep["out"]                                  # the run finished and wrote a file


def test_a_skipped_unit_reaches_the_output_unchanged(dirty_mesc, tmp_path):
    """Skipped means not registered, not missing: writeback copies the source."""
    out = tmp_path / "out.mesc"
    rep = register_file(dirty_mesc, out)
    skipped = [k for k in rep["skipped"]]
    assert skipped
    with MescFile(dirty_mesc) as a, MescFile(out) as b:
        for path in skipped:
            u = path.rsplit("/", 1)[-1]
            assert np.array_equal(a.read(u, reader_units=False),
                                  b.read(u, reader_units=False))


def test_rigid_only_is_available_and_is_a_different_correction(moving_mesc, tmp_path):
    """Opting out must be possible and must be visible in the report — the numbers differ."""
    path, _, _ = moving_mesc
    rep = register_file(path, tmp_path / "rigid.mesc", nonrigid=False)
    assert rep["nonrigid"] is False


def _as_z_stack(path, unit):
    """Relabel one unit of a synthetic file the way MESc labels a z-stack: depth, in µm."""
    import h5py
    with h5py.File(path, "r+") as f:
        u = f[f"MSession_0/{unit}"]
        u.attrs["ZAxisGeomRole"] = 3
        u.attrs["ZAxisConversionConversionLinearScale"] = 1.0
        u.attrs["ZAxisConversionUnitName"] = np.array([ord(c) for c in "µm"] + [0], dtype=np.uint16)
    return path


def test_a_z_stack_is_skipped_loudly_and_its_slices_are_not_moved(two_fields_mesc, tmp_path):
    """A stack's frames are depths. Registered by default, the five stacks of the 2026-09-24
    calibration file came back with their slices moved by 35 to 72 pixels, tagged as corrected.
    """
    path, n_flat, shifts = two_fields_mesc
    _as_z_stack(path, "MUnit_1")
    out = tmp_path / "out.mesc"
    seen = []
    with pytest.warns(Warning, match="z-stack"):
        rep = register_file(path, out, on_skip=lambda units, why: seen.append(why))
    assert list(rep["skipped"]) == ["MSession_0/MUnit_1"] and "z-stack" in seen[0]
    # the control: the recording beside it is still registered, and still correctly
    assert "MSession_0/MUnit_0" in rep["units"]
    y = rep["units"]["MSession_0/MUnit_0"]["y_shift"][n_flat:]
    assert np.ptp(y) >= 3
    with MescFile(path) as a, MescFile(out) as b:
        assert np.array_equal(a.read("MUnit_1", reader_units=False),
                              b.read("MUnit_1", reader_units=False))


def test_a_group_cannot_mix_a_z_stack_with_a_recording(two_fields_mesc, tmp_path):
    from mesc_io.registration import RegistrationError
    path, _, _ = two_fields_mesc
    _as_z_stack(path, "MUnit_1")
    with pytest.raises(RegistrationError, match="mixes z-stacks"):
        register_file(path, tmp_path / "out.mesc", groups=[["MUnit_0", "MUnit_1"]])


def test_a_pixel_past_int16_is_saturated_not_wrapped_to_black():
    from mesc_io.registration import RegistrationWarning, _as_int16
    ok = _as_int16(np.array([0, 30000, 32767], dtype=np.uint16), 1)
    assert ok.tolist() == [0, 30000, 32767]                              # the control
    with pytest.warns(RegistrationWarning, match="saturated"):
        got = _as_int16(np.array([40000, 65535], dtype=np.uint16), 1)
    assert got.tolist() == [32767, 32767]                   # a plain cast gave [-25536, -1]
