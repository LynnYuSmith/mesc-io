"""Exports above 4 GB: ImageJ's own large-stack layout, no alarming warning.

ImageJ cannot read BigTIFF. Above 4 GB tifffile writes what ImageJ writes for large stacks (data
contiguous after the first page) and warns 'truncating ImageJ file'. That layout is correct:
Fiji opens it whole (checked by hand on 4.4 GB, one and two channels). The fast test pins that
only this warning is silenced; the slow one writes a real 4.4 GB file (MESC_IO_SLOW=1).
"""
import os
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

tifffile = pytest.importorskip("tifffile")

from mesc_io.export import _imagej_over_4gb_ok, to_tiff


def test_only_the_truncating_warning_is_silenced():
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with _imagej_over_4gb_ok():
            warnings.warn("<tifffile.TiffWriter 'x.tif'> truncating ImageJ file", UserWarning)
            warnings.warn("something else", UserWarning)
    assert [str(w.message) for w in seen] == ["something else"]


class _BigUnit:
    """A stand-in .mesc with one 512² float unit of n frames; frame i holds i at (0, 0)."""

    def __init__(self, n, nch=1):
        ch = [SimpleNamespace(name=f"Channel_{k}", offset=0.0, scale=1.0, lut=None, colour=None)
              for k in range(nch)]
        self.path = Path("big.mesc")
        self._u = SimpleNamespace(path="MSession_0/MUnit_0", channels=ch, n_frames=n, height=512,
                                  width=512, dtype="uint16", z_step_um=None, frame_rate_hz=30.9,
                                  pixel_size_um=0.5, pixel_size_y_um=None, comment="")

    def unit(self, name):
        return self._u

    def read(self, unit, channel=0, frames=None, reader_units=True):
        idx = np.asarray(list(frames))
        out = np.zeros((len(idx), 512, 512), np.float32)
        out[:, 0, 0] = idx * 10 + channel
        return out


@pytest.mark.skipif(os.environ.get("MESC_IO_SLOW") != "1", reason="writes 4.4 GB; set MESC_IO_SLOW=1")
@pytest.mark.parametrize("nch,n", [(1, 4200), (2, 2100)])
def test_over_4gb_reads_back_whole(tmp_path, nch, n):
    out = tmp_path / "big.tif"
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)        # no warning may reach the user
        to_tiff(_BigUnit(n, nch), "MUnit_0", out, channel="all")
    assert out.stat().st_size > 4 * 2**30
    with tifffile.TiffFile(out) as t:
        assert t.is_imagej and not t.is_bigtiff
        a = t.series[0].asarray(out="memmap")
        assert a.shape[0] == n
        last = a[-1, -1, 0, 0] if nch > 1 else a[-1, 0, 0]
        assert last == (n - 1) * 10 + (nch - 1)
