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
        register_file(dirty_mesc, tmp_path / "x.mesc", units=["MUnit_0", "MUnit_1"])
