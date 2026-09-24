"""A synthetic `.mesc`, built in a fixture.

The tests must run for someone who has no recording of ours — and a real file would be
sharing data, not testing code. So the fixture writes the structure and the attributes a
`.mesc` carries, with values chosen to make each conversion visible.
"""
import h5py
import numpy as np
import pytest

FRAME_PERIOD_MS = 16.152666649956174     # -> 61.909 Hz, a real rig's rate
PIXEL_UM = 0.439453125
OFFSET_CH0 = -786.0
OFFSET_CH1 = -1170.0


def _text(s):
    return np.array([ord(c) for c in s] + [0], dtype=np.uint8)


@pytest.fixture
def mesc(tmp_path):
    path = tmp_path / "synthetic.mesc"
    with h5py.File(path, "w") as f:
        sess = f.create_group("MSession_0")
        for j, (n_frames, comment) in enumerate([(12, "first unit"), (5, "second unit")]):
            u = sess.create_group(f"MUnit_{j}")
            for k, off in enumerate((OFFSET_CH0, OFFSET_CH1)):
                # a ramp, so a wrong offset or a dropped factor is visible in any pixel
                data = (np.arange(n_frames * 4 * 4, dtype=np.uint16)
                        .reshape(n_frames, 4, 4) + 800)
                u.create_dataset(f"Channel_{k}", data=data)
                u.attrs[f"Channel_{k}_Conversion_ConversionLinearOffset"] = off
                u.attrs[f"Channel_{k}_Conversion_ConversionLinearScale"] = 1.0
            u.attrs["ZAxisConversionConversionLinearScale"] = FRAME_PERIOD_MS
            u.attrs["XAxisConversionConversionLinearScale"] = PIXEL_UM
            u.attrs["YAxisConversionConversionLinearScale"] = PIXEL_UM
            u.attrs["Comment"] = _text(comment)
    return path


@pytest.fixture
def mesc_without_rate(tmp_path):
    """A file whose frame period is absent — the rate must come back None, never a default."""
    path = tmp_path / "no_rate.mesc"
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0").create_group("MUnit_0")
        u.create_dataset("Channel_0", data=np.zeros((3, 2, 2), dtype=np.uint16))
    return path


@pytest.fixture
def dirty_mesc(tmp_path):
    """A file that disagrees with itself in every way `check` is meant to notice.

    Modelled on a real session: a z-stack saved beside the recordings reports a frame period
    that is not a frame rate, at half the pixel size and twice the frame width, and one unit
    was aborted after a single frame.
    """
    path = tmp_path / "dirty.mesc"
    with h5py.File(path, "w") as f:
        sess = f.create_group("MSession_0")

        u = sess.create_group("MUnit_0")                      # an ordinary recording
        u.create_dataset("Channel_0", data=np.zeros((10, 4, 4), dtype=np.uint16))
        u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = OFFSET_CH0
        u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
        u.attrs["ZAxisConversionConversionLinearScale"] = FRAME_PERIOD_MS
        u.attrs["XAxisConversionConversionLinearScale"] = PIXEL_UM

        u = sess.create_group("MUnit_1")                      # the z-stack
        u.create_dataset("Channel_0", data=np.zeros((10, 8, 8), dtype=np.uint16))
        u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = OFFSET_CH0
        u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
        u.attrs["ZAxisConversionConversionLinearScale"] = 1.0          # -> "1000 Hz"
        u.attrs["XAxisConversionConversionLinearScale"] = PIXEL_UM / 2

        u = sess.create_group("MUnit_2")                      # aborted, and no conversion
        u.create_dataset("Channel_0", data=np.zeros((1, 4, 4), dtype=np.uint16))
        u.attrs["ZAxisConversionConversionLinearScale"] = FRAME_PERIOD_MS
        u.attrs["XAxisConversionConversionLinearScale"] = PIXEL_UM
    return path


@pytest.fixture
def two_session_mesc(tmp_path):
    """Two sessions, each with a `MUnit_0` — so a bare name cannot identify a recording."""
    path = tmp_path / "two_sessions.mesc"
    with h5py.File(path, "w") as f:
        for si in (0, 1):
            s = f.create_group(f"MSession_{si}")
            for ui in (0, 1):
                u = s.create_group(f"MUnit_{ui}")
                u.create_dataset("Channel_0",
                                 data=np.full((6, 4, 4), 1000 + si * 100 + ui, dtype=np.uint16))
                u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = OFFSET_CH0
                u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
                u.attrs["ZAxisConversionConversionLinearScale"] = FRAME_PERIOD_MS
    return path


@pytest.fixture
def moving_mesc(tmp_path):
    """A recording of a fixed scene that the stage moved under, by shifts we know.

    Nine flat frames at the front (only noise, the state a real recording opens in), then a
    field of blobs displaced by a known sequence. Registration should recover the negatives of
    those displacements and leave the flat head alone.
    """
    rng = np.random.RandomState(0)
    h = w = 128
    scene = np.zeros((h, w), dtype=np.float64)
    ys, xs = np.mgrid[0:h, 0:w]
    for cy, cx, amp in [(30, 40, 900), (70, 90, 1200), (100, 35, 700), (50, 64, 1000)]:
        scene += amp * np.exp(-((ys - cy) ** 2 + (xs - cx) ** 2) / (2 * 3.5 ** 2))

    n_flat, n_move = 9, 40
    shifts = [(0, 0)] * 6 + [(2, -3)] * 8 + [(-4, 1)] * 8 + [(3, 3)] * 8 + [(-1, -2)] * 10
    frames = np.empty((n_flat + n_move, h, w), dtype=np.uint16)
    frames[:n_flat] = (1040 + rng.normal(0, 6, (n_flat, h, w))).clip(0).astype(np.uint16)
    for i, (dy, dx) in enumerate(shifts[:n_move]):
        moved = np.roll(np.roll(scene, dy, axis=0), dx, axis=1)
        frames[n_flat + i] = (1040 + moved + rng.normal(0, 6, (h, w))).clip(0).astype(np.uint16)

    path = tmp_path / "moving.mesc"
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0").create_group("MUnit_0")
        u.create_dataset("Channel_0", data=frames)
        u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = OFFSET_CH0
        u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
        u.attrs["ZAxisConversionConversionLinearScale"] = FRAME_PERIOD_MS
        u.attrs["XAxisConversionConversionLinearScale"] = PIXEL_UM
        u.attrs["Comment"] = _text("a field that moved")
    return path, n_flat, shifts[:n_move]

def _moving_unit(seed, blobs, shifts, n_flat=9, h=128, w=128):
    """Frames of a fixed scene of `blobs` that the stage moved under, by `shifts`."""
    rng = np.random.RandomState(seed)
    scene = np.zeros((h, w), dtype=np.float64)
    ys, xs = np.mgrid[0:h, 0:w]
    for cy, cx, amp in blobs:
        scene += amp * np.exp(-((ys - cy) ** 2 + (xs - cx) ** 2) / (2 * 3.5 ** 2))
    frames = np.empty((n_flat + len(shifts), h, w), dtype=np.uint16)
    frames[:n_flat] = (1040 + rng.normal(0, 6, (n_flat, h, w))).clip(0).astype(np.uint16)
    for i, (dy, dx) in enumerate(shifts):
        moved = np.roll(np.roll(scene, dy, axis=0), dx, axis=1)
        frames[n_flat + i] = (1040 + moved + rng.normal(0, 6, (h, w))).clip(0).astype(np.uint16)
    return frames


@pytest.fixture
def two_fields_mesc(tmp_path):
    """Two units of two DIFFERENT fields, each moved by its own known sequence.

    This is the ordinary shape of a session file, and the case a single shared reference
    gets wrong: the blobs of one field are nowhere in the other.
    """
    shifts_a = [(0, 0)] * 6 + [(2, -3)] * 8 + [(-4, 1)] * 8 + [(3, 3)] * 8 + [(-1, -2)] * 10
    shifts_b = [(0, 0)] * 6 + [(-3, 2)] * 8 + [(1, -4)] * 8 + [(4, 1)] * 8 + [(-2, -1)] * 10
    a = _moving_unit(0, [(30, 40, 900), (70, 90, 1200), (100, 35, 700), (50, 64, 1000)],
                     shifts_a)
    b = _moving_unit(1, [(95, 100, 1100), (20, 105, 800), (60, 20, 950), (110, 70, 700)],
                     shifts_b)

    path = tmp_path / "two_fields.mesc"
    with h5py.File(path, "w") as f:
        sess = f.create_group("MSession_0")
        for name, frames, what in (("MUnit_0", a, "field one"), ("MUnit_1", b, "field two")):
            u = sess.create_group(name)
            u.create_dataset("Channel_0", data=frames)
            u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = OFFSET_CH0
            u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
            u.attrs["ZAxisConversionConversionLinearScale"] = FRAME_PERIOD_MS
            u.attrs["XAxisConversionConversionLinearScale"] = PIXEL_UM
            u.attrs["Comment"] = _text(what)
    return path, 9, {"MUnit_0": shifts_a, "MUnit_1": shifts_b}
