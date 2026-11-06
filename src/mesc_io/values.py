"""Pixel values: what is stored, and what the native reader shows.

A `.mesc` stores unsigned 16-bit integers. The Femtonics reader does not display those: each
channel carries a linear conversion in its attributes, and the reader shows

    displayed = stored * ConversionLinearScale + ConversionLinearOffset

with `scale = 1.0` and a negative offset — the PMT's dark level, different per channel
(typically -786 on the green channel and -1170 on the red, but read it from the file, never
assume it). So a trace pulled straight out of the HDF5 sits on a pedestal of several hundred
counts that the reader has already removed, and two channels of the same recording are not
on the same scale.

Everything here is pure arithmetic on arrays, with the constants supplied by the caller from
the file's own attributes. Nothing is hardcoded and nothing is guessed.
"""
from __future__ import annotations

import numpy as np

from .errors import MescIOError

__all__ = ["to_reader_units", "from_reader_units", "clamp_raw", "ConversionError", "ConversionWarning",
           "InvertWarning"]


class ConversionError(MescIOError, ValueError):
    """A conversion cannot be applied — its scale is zero, so it has no inverse."""


class InvertWarning(UserWarning):
    """The channel was recorded with the PMT A/D inversion OFF (``ad_invert = 0``).

    mesc-io's reader units match MESc on files recorded with ``ad_invert = 1``; no file with 0
    has been checked, so its values may be the wrong way up or on the wrong pedestal. The
    stored integers (``reader_units=False``) are what the file holds either way."""


class ConversionWarning(UserWarning):
    """A channel states no conversion, so "reader units" are the stored integers unchanged."""


def to_reader_units(stored, offset: float, scale: float = 1.0, halved: bool = False,
                    limits=None):
    """Stored integers -> the values the native reader displays.

    `offset` and `scale` come from the channel's `ConversionLinearOffset` /
    `ConversionLinearScale` attributes. Pass `halved=True` when the array has already been
    divided by two somewhere upstream (registration packages that work in int16 commonly do
    this); the factor is then restored before the offset is applied, because the offset is a
    property of the raw integers and not of a scaled copy.

    `limits` is the channel's valid stored range ``(LowerLimit, UpperLimit)``. MESc clamps the
    RAW integers to it before scaling, so this does the same. ``None`` or a range that covers
    the whole stored dtype (0…65535 for uint16, which every file we have checked carries)
    changes nothing and costs no extra pass.

    Returns float64 — the conversion can produce negatives and the caller should see them
    rather than have them clipped away silently. Only the stated raw limits clip anything.
    """
    # one float64 copy, then in place: ``a * scale + offset`` made two more (18 bytes a pixel at
    # the peak where the read guard counts 8 — a 500-frame 512² block was 2.1 GB)
    a = np.array(stored, dtype=np.float64)
    if halved:
        a *= 2.0
    if limits is not None and _narrower(limits, np.uint16 if halved else np.asarray(stored).dtype):
        np.clip(a, float(limits[0]), float(limits[1]), out=a)
    if float(scale) != 1.0:
        a *= float(scale)
    a += float(offset)
    return a


def clamp_raw(raw, limits):
    """The stored integers clamped to a channel's limits, as MESc does before converting.

    For code that reduces the integers (mean, sum) before converting: the clamp must come
    first, because the mean of clamped values is not the clamped mean. Returns `raw` itself,
    untouched, when there are no limits or they cover its whole dtype.
    """
    if limits is None or not _narrower(limits, np.asarray(raw).dtype):
        return raw
    return np.clip(raw, limits[0], limits[1]).astype(np.asarray(raw).dtype, copy=False)


def _narrower(limits, dtype) -> bool:
    """True when `limits` cut into the values `dtype` can hold (so clamping can change data)."""
    lo, hi = float(limits[0]), float(limits[1])
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        return lo > info.min or hi < info.max
    return np.isfinite(lo) or np.isfinite(hi)


def from_reader_units(values, offset: float, scale: float = 1.0, dtype=np.uint16,
                      clip: bool = True):
    """Reader values -> stored integers. The exact inverse of `to_reader_units`.

    This is the direction that writes back into a file, so it clips to the target dtype's
    range by default: a value outside it means the data is not what this conversion describes,
    and silently wrapping around would corrupt the file.

    Values that `to_reader_units` clamped to a channel's limits cannot be recovered: the inverse
    returns the limit, as MESc itself would show it.
    """
    if float(scale) == 0.0:
        raise ConversionError("conversion scale is zero — cannot invert")
    a = (np.asarray(values, dtype=np.float64) - float(offset)) / float(scale)
    if np.issubdtype(np.dtype(dtype), np.integer):
        a = np.rint(a)          # nearest, not towards zero: truncating biased every value by -0.5
    if clip:
        info = np.iinfo(dtype)
        a = np.clip(a, info.min, info.max)
    return a.astype(dtype)
