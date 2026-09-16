"""Write one unit out — to HDF5, or to a TIFF stack.

Two decisions this module makes deliberately, because getting them wrong quietly is the
usual way a export goes bad:

* **The dtype follows the units.** Reader values can be negative (a pixel below the PMT's
  dark level), so they are written as float32. Stored values stay in the file's own integer
  type. There is no mode that writes converted values into a uint16 and clips the negatives
  away without saying so.
* **The metadata travels with the pixels.** Frame rate, pixel size and the conversion that
  produced the values are written as attributes, so the exported file can still answer the
  questions the `.mesc` could. A TIFF gets them in its ImageJ description, which is what
  ImageJ and Fiji read back as frame interval and spatial scale.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import h5py
import numpy as np

__all__ = ["to_hdf5", "to_tiff"]


def _block(mesc, unit: str, channel: int, frames, reader_units: bool):
    u = mesc.unit(unit)
    data = mesc.read(unit, channel=channel, frames=frames, reader_units=reader_units)
    return u, (np.asarray(data, dtype=np.float32) if reader_units else np.asarray(data))


def to_hdf5(mesc, unit: str, out_path, channel: int = 0, dataset: str = "data",
            frames=None, reader_units: bool = True, compression: Optional[str] = "lzf"):
    """One unit's channel into an HDF5 dataset, with its metadata as attributes.

    Returns the path written.
    """
    u, data = _block(mesc, unit, channel, frames, reader_units)
    ch = u.channels[channel]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(str(out_path), "w") as f:
        ds = f.create_dataset(dataset, data=data, compression=compression)
        ds.attrs["source_file"] = mesc.path.name
        ds.attrs["source_unit"] = u.path
        ds.attrs["source_channel"] = ch.name
        ds.attrs["units"] = "reader" if reader_units else "stored"
        ds.attrs["conversion_offset"] = ch.offset
        ds.attrs["conversion_scale"] = ch.scale
        if u.frame_rate_hz:
            ds.attrs["frame_rate_hz"] = u.frame_rate_hz
        if u.pixel_size_um:
            ds.attrs["pixel_size_um"] = u.pixel_size_um
        if u.comment:
            ds.attrs["source_comment"] = u.comment
    return out_path


def to_tiff(mesc, unit: str, out_path, channel: int = 0, frames=None,
            reader_units: bool = True):
    """One unit's channel as a TIFF stack ImageJ can open with the right scales.

    Needs `tifffile` (`pip install mesc-io[tiff]`).
    """
    try:
        import tifffile
    except ImportError as exc:  # noqa: BLE001
        raise ImportError("writing TIFF needs tifffile — pip install mesc-io[tiff]") from exc
    u, data = _block(mesc, unit, channel, frames, reader_units)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"axes": "TYX"}
    if u.frame_rate_hz:
        meta["finterval"] = 1.0 / u.frame_rate_hz
        meta["fps"] = u.frame_rate_hz
    res = None
    if u.pixel_size_um:
        meta["unit"] = "um"
        res = (1.0 / u.pixel_size_um, 1.0 / u.pixel_size_um)
    tifffile.imwrite(str(out_path), data, imagej=True, metadata=meta, resolution=res)
    return out_path
