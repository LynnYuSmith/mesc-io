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
