"""Put processed frames back into a `.mesc` the native reader still opens.

Registration, denoising and background correction all happen outside the Femtonics software,
and the result usually stays outside it too — in a TIFF or an HDF5 nobody at the rig opens.
Writing the frames back into a `.mesc` puts the processed movie where a collaborator already
knows how to look at it.

Three things this does deliberately, each because the opposite fails quietly:

* **It copies the file and edits the copy.** A `.mesc` carries far more than pixels, and
  rebuilding one from scratch loses whatever this version of the format keeps that we do not
  know about. The copy keeps all of it and only the frame data changes.
* **It checks the conversion against the file before writing a single frame.** Processed
  frames arrive in whatever units the caller worked in, and getting that wrong writes a
  plausible-looking movie with the wrong intensities — the failure nobody catches, because
  the picture still looks like the tissue. So the new frames are compared with the ones they
  replace, on a shift-invariant statistic, and a disagreement aborts rather than writes.
* **It marks the unit.** A tag is appended to the comment, so a corrected file can never be
  mistaken for the original in a folder listing or in the reader.

Frames shorter than the original are aligned to the **end** of the recording, on the
assumption that whatever was dropped came off the front (dark frames at the start are the
usual reason). Anything longer is refused.
"""
from __future__ import annotations

import os
import shutil
import zlib
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional

import h5py
import numpy as np
from h5py import h5z
from h5py._objects import phil as _phil

from .errors import MescIOError
from .values import from_reader_units

__all__ = ["write_frames", "WritebackError", "DEFAULT_TAG"]

DEFAULT_TAG = "_MC"
#: Frames converted and written per step. The conversion to stored integers goes through
#: float64, so converting a whole unit at once peaked at 8x its stored size (15.6 GB for one
#: channel of 3,715 frames of 512^2); 64 frames of 512^2 is 128 MB of float64.
_CHUNK = 64
#: Threads that deflate frames for the one-chunk-per-frame write path. Only zlib runs in them.
_DEFLATE_THREADS = max(1, min(8, os.cpu_count() or 1))


class WritebackError(MescIOError, RuntimeError):
    """The frames do not fit, or do not agree with the file they would replace."""


def _append_tag(unit_grp, tag: str) -> None:
    """Append `tag` to the unit's comment, in both spellings the format uses. Idempotent."""
    if "CommentDebugString" in unit_grp.attrs:
        s = unit_grp.attrs["CommentDebugString"]
        s = s.decode("utf-8", "ignore") if isinstance(s, (bytes, np.bytes_)) else str(s)
        if not s.rstrip("\x00").endswith(tag):
            unit_grp.attrs["CommentDebugString"] = (s.rstrip("\x00") + tag).encode("utf-8")
    if "Comment" in unit_grp.attrs:
        c = np.asarray(unit_grp.attrs["Comment"])
        body = c[c != 0]
        if "".join(chr(int(x)) for x in body).endswith(tag):
            return
        add = np.array([ord(ch) for ch in tag], dtype=c.dtype)
        unit_grp.attrs["Comment"] = np.concatenate(
            [body, add, np.array([0], c.dtype)]).astype(c.dtype)
    else:
        # A unit with no comment would otherwise come out unmarked, and a corrected copy that
        # cannot be told from its source is the situation the tag exists to prevent.
        unit_grp.attrs["Comment"] = np.array([ord(ch) for ch in tag] + [0], dtype=np.uint8)


def _resolve_unit(f, sessions, name: str, filename: str) -> str:
    """`MSession_i/MUnit_j` for `name`, which may be a full path or a bare unit name.

    A file with more than one session can hold two units of the same name. Silently taking the
    first would write over the wrong recording, so an ambiguous name is refused with the paths
    to choose from — the same rule the reader applies.
    """
    if "/" in name:
        if name in f:
            return name
        raise WritebackError(f"{name} is not in {filename}")
    hits = [f"{s}/{name}" for s in sessions if name in f[s]]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise WritebackError(
            f"{name!r} is ambiguous in {filename} — it exists in {len(hits)} sessions "
            f"({', '.join(hits)}). Name the one you mean.")
    raise WritebackError(f"{name} is not in {filename}")


def _agreement(new_stored, original, offset_frames: int, n_sample: int = 4) -> float:
    """Median over sampled frames of `original − new`, in stored units.

    A per-frame median is nearly unchanged by a translation, so this compares the two movies
    without being fooled by the registration shifts that are the whole point of the exercise.
    Zero means the caller's units match the file's.
    """
    n = new_stored.shape[0]
    idx = np.unique(np.linspace(n // 5, max(n - n // 5 - 1, 0), n_sample).astype(int))
    diffs = [float(np.median(original[offset_frames + int(i)].astype(np.float64))
                   - np.median(np.asarray(new_stored[int(i)], dtype=np.float64)))
             for i in idx]
    return float(np.median(diffs))


class _Converted:
    """`arr` as stored integers, converted only for the frames that are asked for.

    The conversion is element-wise, so a frame converted on its own is the same frame the
    whole array would have given — without holding the whole array as float64.
    """

    def __init__(self, arr: np.ndarray, convert: Callable[[np.ndarray], np.ndarray]):
        self.arr, self.convert, self.shape = arr, convert, arr.shape

    def __getitem__(self, i: int) -> np.ndarray:
        return self.convert(self.arr[i:i + 1])[0]


def _converter(attrs, channel: str, reader_units: bool, dtype) -> Callable:
    """The function that turns a block of the caller's frames into the file's integers."""
    if reader_units:
        off = float(attrs.get(f"{channel}_Conversion_ConversionLinearOffset", 0.0))
        sc = float(attrs.get(f"{channel}_Conversion_ConversionLinearScale", 1.0))
        return partial(from_reader_units, offset=off, scale=sc, dtype=dtype)
    return lambda block: np.asarray(block).astype(dtype, copy=False)


def _check_channel(f, unit_path: str, channel: str, arr, reader_units: bool,
                   tolerance: float):
    """Validate one channel against `f` (the source, or a copy not yet written to).

    Returns `(array, convert, lead, agreement)`; raises `WritebackError` on any mismatch.
    """
    if channel not in f[unit_path]:
        raise WritebackError(f"{unit_path} has no {channel}")
    original = f[unit_path][channel]
    a = np.asarray(arr)
    if a.ndim != 3 or a.shape[1:] != original.shape[1:]:
        raise WritebackError(
            f"{unit_path}/{channel}: frames are {a.shape}, the file holds "
            f"{original.shape} — frame size must match")
    lead = original.shape[0] - a.shape[0]
    if lead < 0:
        raise WritebackError(
            f"{unit_path}/{channel}: {a.shape[0]} frames offered, the file holds "
            f"only {original.shape[0]}")
    convert = _converter(f[unit_path].attrs, channel, reader_units, original.dtype)
    delta = _agreement(_Converted(a, convert), original, lead)
    if abs(delta) > tolerance:
        raise WritebackError(
            f"{unit_path}/{channel}: the frames differ from the ones they would "
            f"replace "
            f"by {delta:.0f} counts (tolerance {tolerance:.0f}) — refusing to "
            f"write. Check whether they are in the units you think they are.")
    return a, convert, lead, delta


def _frame_deflate_level(ds) -> Optional[int]:
    """The gzip level, if `ds` is one deflate-only chunk per frame; else None.

    That is the layout MESc writes, and the only one the threaded path handles: one frame is
    one chunk, so a frame can be deflated on its own and handed to HDF5 as the finished chunk.
    Shuffle, Fletcher32, scale-offset or any other filter — or chunks that are not exactly one
    frame — go through h5py as before.
    """
    try:
        if ds.ndim != 3 or ds.chunks is None or tuple(ds.chunks) != (1,) + tuple(ds.shape[1:]):
            return None
        if ds.dtype.kind not in "ui" or ds.is_virtual or ds.external:
            return None
        dcpl = ds.id.get_create_plist()
        if dcpl.get_nfilters() != 1:
            return None
        code, _flags, values, _name = dcpl.get_filter(0)
        if code != h5z.FILTER_DEFLATE or len(values) != 1:
            return None
        return int(values[0])
    except Exception:                       # noqa: BLE001 — anything unusual takes h5py's path
        return None


def _write_channel(ds, a: np.ndarray, convert: Callable, lead: int, block: int,
                   pool: Optional[ThreadPoolExecutor]) -> str:
    """Write `a` (the caller's frames) into `ds` from frame `lead`, `block` frames at a time.

    For a one-chunk-per-frame deflate dataset the frames are deflated with `zlib` in `pool`
    and handed to HDF5 as finished chunks; HDF5's deflate filter is zlib's `compress2` at the
    dataset's level, so the stored chunks are the same bytes h5py would have written — and
    that is checked on the first frame, which is written through h5py and compared, falling
    back to h5py for the whole channel if they differ (a Python linked against another zlib).
    Only zlib runs in the threads: HDF5 is not thread-safe, so every h5py call is made here,
    in this thread, under h5py's own lock. Returns the path taken, "deflate" or "h5py".
    """
    n = a.shape[0]
    level = _frame_deflate_level(ds) if pool is not None else None
    path = "h5py"
    c0 = 0
    if level is not None and n:
        first = np.ascontiguousarray(convert(a[0:1]))
        with _phil:
            ds[lead:lead + 1] = first
            mask, stored = ds.id.read_direct_chunk((lead,) + (0,) * (ds.ndim - 1))
        if (first.dtype == ds.dtype and mask == 0
                and bytes(stored) == zlib.compress(first[0].tobytes(), level)):
            path, c0 = "deflate", 1
        else:
            level = None
            c0 = 1                                  # the first frame is already in
    while c0 < n:
        c1 = min(c0 + block, n)
        s = np.ascontiguousarray(convert(a[c0:c1]))
        if level is not None:
            packed = list(pool.map(partial(zlib.compress, level=level),
                                   [s[i] for i in range(s.shape[0])]))
            with _phil:
                for i, chunk_bytes in enumerate(packed):
                    ds.id.write_direct_chunk((lead + c0 + i,) + (0,) * (ds.ndim - 1),
                                             chunk_bytes)
        else:
            with _phil:
                ds[lead + c0:lead + c1] = s
        c0 = c1
    return path


def write_frames(source, out, frames: Mapping[str, Mapping[str, np.ndarray]],
                 reader_units: bool = True, tag: Optional[str] = DEFAULT_TAG,
                 tolerance: float = 60.0, chunk: int = _CHUNK) -> Dict:
    """Copy `source` to `out` and replace the frames of the units named in `frames`.

    `frames` is `{unit: {channel: array}}`, e.g. `{"MUnit_0": {"Channel_0": arr}}`, where the
    array is `(n_frames, height, width)`. With `reader_units=True` the arrays hold the values
    the native reader displays and are converted back using each channel's own conversion
    attributes; with False they are written as-is.

    `tolerance` is how far, in stored counts, the new frames may differ from the ones they
    replace before the write is refused. Raise it only if you know why they differ.

    Returns a report: which units and channels were written, and the measured agreement for
    each. Raises `WritebackError` before writing anything if any channel disagrees.
    """
    source, out = Path(source), Path(out)
    if not source.exists():
        raise FileNotFoundError(source)
    report = {"out": str(out), "written": [], "agreement": {}, "warnings": []}

    # Validate everything first, against the SOURCE, so a refusal leaves no half-written copy.
    # Only the few frames the agreement samples are converted here; the rest are converted
    # block by block as they are written.
    with h5py.File(str(source), "r") as f:
        sessions = [k for k in f if k.startswith("MSession_")]
        if not sessions:
            raise WritebackError(f"{source.name}: no MSession_* group — not a .mesc?")
        plan = []
        for unit, per_channel in frames.items():
            unit_path = _resolve_unit(f, sessions, unit, source.name)
            for channel, arr in per_channel.items():
                a, convert, lead, delta = _check_channel(f, unit_path, channel, arr,
                                                         reader_units, tolerance)
                report["agreement"][f"{unit_path}/{channel}"] = delta
                plan.append((unit_path, channel, a, convert, lead))
                if lead:
                    report["warnings"].append(
                        f"{unit_path}/{channel}: {lead} frame(s) shorter — aligned to the end")

    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, out)
    with _Output(out, tag=tag, chunk=chunk) as dest:
        for unit_path, channel, a, convert, lead in plan:
            dest.write(unit_path, channel, a, convert, lead)
            report["written"].append(f"{unit_path}/{channel}")
        for unit_path in dict.fromkeys(u for u, *_ in plan):
            dest.tag(unit_path)
    return report


class _Output:
    """An open copy of a `.mesc` that frames are written into, one channel at a time.

    `write_frames` validates everything first and then writes; registration writes each unit
    as soon as it is registered (`put`), so only one unit is ever held in memory.
    """

    def __init__(self, path, tag: Optional[str] = DEFAULT_TAG, chunk: int = _CHUNK,
                 threads: int = _DEFLATE_THREADS):
        self.path, self._tag, self.chunk = Path(path), tag, max(1, int(chunk))
        self._threads = threads
        self.paths_taken: Dict[str, str] = {}

    def __enter__(self):
        with _phil:
            self.d = h5py.File(str(self.path), "r+")
        self.pool = ThreadPoolExecutor(self._threads) if self._threads > 1 else None
        return self

    def __exit__(self, *exc):
        if self.pool is not None:
            self.pool.shutdown(wait=True)
        with _phil:
            self.d.close()
        return False

    def write(self, unit_path: str, channel: str, a, convert, lead: int) -> None:
        ds = self.d[unit_path][channel]
        self.paths_taken[f"{unit_path}/{channel}"] = _write_channel(
            ds, a, convert, lead, self.chunk, self.pool)

    def tag(self, unit_path: str) -> None:
        if self._tag:
            with _phil:
                _append_tag(self.d[unit_path], self._tag)

    def put(self, unit: str, per_channel: Mapping[str, np.ndarray], reader_units: bool,
            tolerance: float) -> Dict[str, float]:
        """Validate one unit against the copy (which still holds its original frames), then
        write and tag it. Returns the agreement per channel."""
        sessions = [k for k in self.d if k.startswith("MSession_")]
        unit_path = _resolve_unit(self.d, sessions, unit, self.path.name)
        checked = [(ch,) + _check_channel(self.d, unit_path, ch, arr, reader_units, tolerance)
                   for ch, arr in per_channel.items()]
        for ch, a, convert, lead, _ in checked:
            self.write(unit_path, ch, a, convert, lead)
        if checked:
            self.tag(unit_path)
        return {f"{unit_path}/{ch}": delta for ch, _, _, _, delta in checked}
