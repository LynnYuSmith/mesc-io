"""Load frames back from whatever they were exported into.

`export` writes an HDF5 or a TIFF and records, in the file, which units the values are in.
`writeback` reads that record instead of asking the user to remember it — which is the whole
point, since "did I process the reader values or the stored integers?" is exactly the thing a
person forgets between exporting on Monday and writing back on Friday, and getting it wrong
produces a file that looks right.

A file this package did not write carries no such record, and then the units have to be
stated. Guessing from the dtype would be a coin flip dressed as a feature.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .errors import MescIOError

__all__ = ["load_frames", "FramesFormatError"]


class FramesFormatError(MescIOError, ValueError):
    """The frames could not be read, or do not say which units they are in."""


def load_frames(path, dataset: Optional[str] = None) -> Tuple[np.ndarray, Optional[bool]]:
    """`(frames, reader_units)` from an `.h5` or a `.tif`.

    `reader_units` is True, False, or **None** when the file does not say — in which case the
    caller must be told by a human which it is.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".h5", ".hdf5"):
        return _from_hdf5(path, dataset)
    if suffix in (".tif", ".tiff"):
        return _from_tiff(path)
    raise FramesFormatError(
        f"{path.name}: expected .h5 or .tif, got {suffix or 'no suffix'}")


def _from_hdf5(path: Path, dataset: Optional[str]):
    import h5py
    with h5py.File(str(path), "r") as f:
        if dataset is None:
            candidates = [k for k, v in f.items() if isinstance(v, h5py.Dataset)
                          and getattr(v, "ndim", 0) == 3]
            if len(candidates) != 1:
                raise FramesFormatError(
                    f"{path.name}: {'no' if not candidates else len(candidates)} three-"
                    f"dimensional dataset(s) at the top level"
                    + (f" ({', '.join(candidates)}) — name one with --dataset"
                       if candidates else ""))
            dataset = candidates[0]
        if dataset not in f:
            raise FramesFormatError(f"{path.name} has no dataset {dataset!r}")
        ds = f[dataset]
        units = ds.attrs.get("units")
        if isinstance(units, bytes):
            units = units.decode()
        flag = {"reader": True, "stored": False}.get(str(units)) if units is not None else None
        return np.asarray(ds[:]), flag


def _from_tiff(path: Path):
    try:
        import tifffile
    except ImportError as exc:  # noqa: BLE001
        raise ImportError("reading TIFF needs tifffile — pip install mesc-io[tiff]") from exc
    with tifffile.TiffFile(str(path)) as t:
        data = t.asarray()
    if data.ndim != 3:
        raise FramesFormatError(f"{path.name}: expected a stack, got shape {data.shape}")
    # A TIFF carries no units record of ours; float means it came out converted, but "means"
    # is not "says", so this stays a None and the caller has to be sure.
    return data, None
