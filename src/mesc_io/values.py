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

__all__ = ["to_reader_units", "from_reader_units", "ConversionError"]


class ConversionError(ValueError):
    """A file's conversion attributes are missing, or disagree with its own data."""


def to_reader_units(stored, offset: float, scale: float = 1.0, halved: bool = False):
    """Stored integers -> the values the native reader displays.

    `offset` and `scale` come from the channel's `ConversionLinearOffset` /
    `ConversionLinearScale` attributes. Pass `halved=True` when the array has already been
    divided by two somewhere upstream (registration packages that work in int16 commonly do
    this); the factor is then restored before the offset is applied, because the offset is a
    property of the raw integers and not of a scaled copy.

    Returns float64 — the conversion can produce negatives and the caller should see them
    rather than have them clipped away silently.
    """
    a = np.asarray(stored, dtype=np.float64)
    if halved:
        a = a * 2.0
    return a * float(scale) + float(offset)


def from_reader_units(values, offset: float, scale: float = 1.0, dtype=np.uint16,
                      clip: bool = True):
    """Reader values -> stored integers. The exact inverse of `to_reader_units`.

    This is the direction that writes back into a file, so it clips to the target dtype's
    range by default: a value outside it means the data is not what this conversion describes,
    and silently wrapping around would corrupt the file.
    """
    if float(scale) == 0.0:
        raise ConversionError("conversion scale is zero — cannot invert")
    a = (np.asarray(values, dtype=np.float64) - float(offset)) / float(scale)
    if clip:
        info = np.iinfo(dtype)
        a = np.clip(a, info.min, info.max)
    return a.astype(dtype)
