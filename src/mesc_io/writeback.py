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

import shutil
from pathlib import Path
from typing import Dict, Mapping, Optional

import h5py
import numpy as np

from .errors import MescIOError
from .values import from_reader_units

__all__ = ["write_frames", "WritebackError", "DEFAULT_TAG"]

DEFAULT_TAG = "_MC"
_CHUNK = 500


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
    with h5py.File(str(source), "r") as f:
        sessions = [k for k in f if k.startswith("MSession_")]
        if not sessions:
            raise WritebackError(f"{source.name}: no MSession_* group — not a .mesc?")
        plan = []
        for unit, per_channel in frames.items():
            unit_path = _resolve_unit(f, sessions, unit, source.name)
            for channel, arr in per_channel.items():
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
                attrs = f[unit_path].attrs
                off = attrs.get(f"{channel}_Conversion_ConversionLinearOffset", 0.0)
                sc = attrs.get(f"{channel}_Conversion_ConversionLinearScale", 1.0)
                stored = (from_reader_units(a, offset=float(off), scale=float(sc),
                                            dtype=original.dtype)
                          if reader_units else a.astype(original.dtype))
                delta = _agreement(stored, original, lead)
                if abs(delta) > tolerance:
                    raise WritebackError(
                        f"{unit_path}/{channel}: the frames differ from the ones they would "
                        f"replace "
                        f"by {delta:.0f} counts (tolerance {tolerance:.0f}) — refusing to "
                        f"write. Check whether they are in the units you think they are.")
                report["agreement"][f"{unit_path}/{channel}"] = delta
                plan.append((unit_path, channel, stored, lead))
                if lead:
                    report["warnings"].append(
                        f"{unit_path}/{channel}: {lead} frame(s) shorter — aligned to the end")

    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, out)
    with h5py.File(str(out), "r+") as d:
        for unit_path, channel, stored, lead in plan:
            ds = d[unit_path][channel]
            n = stored.shape[0]
            for c0 in range(0, n, chunk):
                c1 = min(c0 + chunk, n)
                ds[lead + c0:lead + c1] = stored[c0:c1]
            report["written"].append(f"{unit_path}/{channel}")
        if tag:
            for unit_path in {u for u, _, _, _ in plan}:
                _append_tag(d[unit_path], tag)
    return report
