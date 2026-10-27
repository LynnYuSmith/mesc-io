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


def _selection(u, frames):
    """The frame indices a ``frames`` argument (None, slice, int, indices) stands for."""
    n = u.n_frames
    if frames is None:
        return list(range(n))
    if isinstance(frames, slice):
        return list(range(n)[frames])
    if isinstance(frames, (int, np.integer)):
        return [range(n)[frames]]
    return [range(n)[int(i)] for i in np.asarray(frames).ravel()]


def to_hdf5(mesc, unit: str, out_path, channel: int = 0, dataset: str = "data",
            frames=None, reader_units: bool = True, compression: Optional[str] = "lzf",
            block: int = 256):
    """One unit's channel into an HDF5 dataset, with its metadata as attributes.

    Written a block of frames at a time, so a unit larger than memory exports too: a whole
    3,715-frame 512² unit was refused before (7.8 GB as float64, over the read guard).

    Returns the path written.
    """
    u = mesc.unit(unit)
    ch = u.channels[channel]
    sel = _selection(u, frames)
    dtype = np.float32 if reader_units else np.dtype(u.dtype)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(str(out_path), "w") as f:
        ds = f.create_dataset(dataset, shape=(len(sel), u.height, u.width), dtype=dtype,
                              chunks=(1, u.height, u.width) if sel else None, compression=compression)
        for s in range(0, len(sel), block):
            part = sel[s:s + block]
            ds[s:s + len(part)] = np.asarray(
                mesc.read(unit, channel=channel, frames=part, reader_units=reader_units), dtype)
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


_DEFAULT_COLOURS = ("#00ff00", "#ff00ff", "#00ffff", "#ffff00")


def _lut(colour: str) -> np.ndarray:
    """An ImageJ LUT (3 × 256, uint8) running from black to ``colour``."""
    rgb = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    ramp = np.arange(256, dtype=np.float64) / 255.0
    return np.stack([np.round(ramp * c) for c in rgb]).astype(np.uint8)


def _info(mesc, u, chans, reader_units: bool) -> str:
    lines = [f"source_file = {mesc.path.name}", f"source_unit = {u.path}",
             f"units = {'reader' if reader_units else 'stored'}"]
    if u.comment:
        lines.append(f"comment = {u.comment}")
    if u.frame_rate_hz:
        lines.append(f"frame_rate_hz = {u.frame_rate_hz}")
    if u.z_step_um:
        lines.append(f"z_step_um = {u.z_step_um}")
    if u.pixel_size_um:
        lines.append(f"pixel_size_um = {u.pixel_size_um}")
    if u.pixel_size_y_um:
        lines.append(f"pixel_size_y_um = {u.pixel_size_y_um}")
    for c in chans:
        lines.append(f"{c.name}: conversion_offset = {c.offset}, conversion_scale = {c.scale}"
                     + (f", rig LUT = {c.lut[0]:g}..{c.lut[1]:g}" if c.lut else ""))
    return "\n".join(lines)


def to_tiff(mesc, unit: str, out_path, channel=0, frames=None,
            reader_units: bool = True, block: int = 256):
    """A unit as a TIFF stack ImageJ / Fiji opens with the right scales.

    ``channel`` an index writes that one channel (axes TYX, or ZYX for a z-stack). ``channel="all"``
    writes every channel as one ImageJ hyperstack (TCYX, or ZCYX), in composite mode: each channel
    in its own colour (the file's, else green / magenta) and its own display range (1–99.8 % of
    that channel, so a red ten times brighter does not set the window for the green). A z-stack
    carries its slice spacing, a time series its frame interval; x and y keep their own pixel
    sizes. The comment, the units and each channel's conversion go into the image's Info
    (Image ▸ Show Info in Fiji). Frames are read and written a block at a time, so a long unit
    never sits in memory whole.

    Needs `tifffile` (`pip install mesc-io[tiff]`).
    """
    try:
        import tifffile
    except ImportError as exc:  # noqa: BLE001
        raise ImportError("writing TIFF needs tifffile — pip install mesc-io[tiff]") from exc
    u = mesc.unit(unit)
    idx = list(range(len(u.channels))) if channel in ("all", None) else [int(channel)]
    chans = [u.channels[i] for i in idx]
    sel = range(u.n_frames)[frames] if isinstance(frames, slice) else (
        list(frames) if frames is not None else range(u.n_frames))
    sel = list(sel)
    n, h, w, nc = len(sel), u.height, u.width, len(idx)
    dtype = np.float32 if reader_units else np.dtype(u.dtype)
    depth = bool(u.z_step_um)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    meta = {"axes": ("Z" if depth else "T") + ("C" if nc > 1 else "") + "YX",
            "Info": _info(mesc, u, chans, reader_units)}
    if depth:
        meta["spacing"] = float(u.z_step_um)
    elif u.frame_rate_hz:
        meta["finterval"] = 1.0 / u.frame_rate_hz
        meta["fps"] = u.frame_rate_hz
    res = None
    if u.pixel_size_um:
        meta["unit"] = "um"
        res = (1.0 / u.pixel_size_um, 1.0 / (u.pixel_size_y_um or u.pixel_size_um))
    if nc > 1:
        # one window per channel, from frames spread over the unit (never one shared window)
        probe = sel[:: max(1, n // 64)][:64]
        ranges = []
        for i in idx:
            a = np.asarray(mesc.read(unit, channel=i, frames=probe, reader_units=reader_units), np.float64)
            lo, hi = np.percentile(a, [1, 99.8])
            ranges += [float(lo), float(hi if hi > lo else lo + 1)]
        meta["mode"] = "composite"
        meta["Ranges"] = tuple(ranges)
        meta["LUTs"] = [_lut(c.colour if c.colour and c.colour.lower() not in ("#000000",) else
                             _DEFAULT_COLOURS[k % len(_DEFAULT_COLOURS)]) for k, c in enumerate(chans)]

    def pages():
        for s in range(0, n, block):
            part = sel[s:s + block]
            stack = [np.asarray(mesc.read(unit, channel=i, frames=part, reader_units=reader_units), dtype)
                     for i in idx]
            for t in range(len(part)):
                for k in range(nc):
                    yield stack[k][t]

    shape = (n, nc, h, w) if nc > 1 else (n, h, w)
    tifffile.imwrite(str(out_path), pages(), shape=shape, dtype=dtype, imagej=True,
                     metadata=meta, resolution=res, bigtiff=False)
    return out_path
