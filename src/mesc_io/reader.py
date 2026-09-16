"""Open a `.mesc` and ask it what it contains.

A `.mesc` is an HDF5 file laid out as `MSession_<i>/MUnit_<j>/Channel_<k>`, where a *unit* is
one continuous recording and a *channel* is one detector. The things you need in order to use
the data are not where you would look for them:

* the **frame rate** is not stored. What is stored is the frame *period*, in milliseconds, as
  `ZAxisConversionConversionLinearScale` on the unit. The rate is its reciprocal, and it
  differs from unit to unit within one file — a recording set up at "60 Hz" comes back at
  61.909 Hz, and using the nominal number instead bakes a percent-level error into every
  time-dependent quantity downstream;
* the **pixel size** in micrometres is `X/YAxisConversionConversionLinearScale`;
* the **pixel values** are not what the reader shows — see `mesc_io.values`;
* the unit's `Comment` is free text a human typed at the rig. This package returns it
  verbatim and never parses it: what a lab writes there is that lab's convention.

Read-only. Nothing here modifies a file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import h5py
import numpy as np

from .values import to_reader_units

__all__ = ["MescFile", "Unit", "Channel", "MescError"]


class MescError(RuntimeError):
    """The file is not shaped like a `.mesc`, or is missing something required."""


def _text(value) -> str:
    """Femtonics writes strings as NUL-terminated uint8/uint16 arrays as often as bytes."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace").rstrip("\x00").strip()
    if isinstance(value, np.ndarray):
        return "".join(chr(int(c)) for c in value.ravel() if int(c)).strip()
    return str(value).strip()


@dataclass(frozen=True)
class Channel:
    """One detector of one unit, with the conversion that makes its values meaningful."""
    index: int
    name: str
    offset: float
    scale: float

    @property
    def dataset(self) -> str:
        return self.name


@dataclass(frozen=True)
class Unit:
    """One continuous recording."""
    name: str
    session: str
    n_frames: int
    height: int
    width: int
    dtype: str
    frame_rate_hz: Optional[float]
    pixel_size_um: Optional[float]
    comment: str
    channels: List[Channel]

    @property
    def shape(self):
        return (self.n_frames, self.height, self.width)

    @property
    def duration_s(self) -> Optional[float]:
        if not self.frame_rate_hz:
            return None
        return self.n_frames / self.frame_rate_hz

    @property
    def path(self) -> str:
        return f"{self.session}/{self.name}"


def _attr(attrs, name):
    return attrs[name] if name in attrs else None


def _float_or_none(value) -> Optional[float]:
    try:
        f = float(np.ravel(value)[0]) if isinstance(value, np.ndarray) else float(value)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


class MescFile:
    """Read-only handle on a `.mesc`. Use as a context manager."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self._f = h5py.File(str(self.path), "r")
        self._units: Optional[Dict[str, Unit]] = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        if self._f is not None:
            self._f.close()
            self._f = None

    # -- structure ---------------------------------------------------------
    def sessions(self) -> List[str]:
        return [k for k in self._f.keys() if k.startswith("MSession_")]

    def units(self) -> List[Unit]:
        """Every unit in the file, in numeric order, with its metadata resolved."""
        if self._units is None:
            found: Dict[str, Unit] = {}
            for s in self.sessions():
                for name in sorted(self._f[s], key=_unit_sort_key):
                    u = self._read_unit(s, name)
                    if u is not None:
                        found[u.path] = u
            if not found:
                raise MescError(f"{self.path.name}: no MSession_*/MUnit_* groups — not a .mesc?")
            self._units = found
        return list(self._units.values())

    def unit(self, name: str) -> Unit:
        """One unit by `MUnit_3` or by its full `MSession_0/MUnit_3` path."""
        for u in self.units():
            if name in (u.name, u.path):
                return u
        raise KeyError(f"{name!r} not in {self.path.name}")

    # -- pixels ------------------------------------------------------------
    def read(self, unit: str, channel: int = 0, frames=None, reader_units: bool = True):
        """Frames of one channel. `frames` is a slice or index array; None means all.

        With `reader_units=True` (the default) the values are what the native Femtonics
        reader displays, as float64. With False you get the stored integers untouched.
        """
        u = self.unit(unit)
        try:
            ch = u.channels[channel] if isinstance(channel, int) else next(
                c for c in u.channels if c.name == channel)
        except (IndexError, StopIteration):
            raise KeyError(f"{u.path} has no channel {channel!r} "
                           f"(has {[c.name for c in u.channels]})") from None
        ds = self._f[f"{u.path}/{ch.dataset}"]
        block = ds[:] if frames is None else ds[frames]
        if not reader_units:
            return block
        return to_reader_units(block, offset=ch.offset, scale=ch.scale)

    # -- internals ---------------------------------------------------------
    def _read_unit(self, session: str, name: str) -> Optional[Unit]:
        grp = self._f[f"{session}/{name}"]
        if not isinstance(grp, h5py.Group):
            return None
        chan_names = sorted(k for k in grp if k.startswith("Channel_"))
        if not chan_names:
            return None
        a = grp.attrs
        channels = []
        for i, cn in enumerate(chan_names):
            off = _float_or_none(_attr(a, f"{cn}_Conversion_ConversionLinearOffset"))
            sc = _float_or_none(_attr(a, f"{cn}_Conversion_ConversionLinearScale"))
            channels.append(Channel(index=i, name=cn,
                                    offset=0.0 if off is None else off,
                                    scale=1.0 if sc is None else sc))
        first = grp[chan_names[0]]
        n, h, w = (first.shape + (0, 0, 0))[:3]
        # frame PERIOD in ms -> rate in Hz. Guard the reciprocal: a zero or absent scale is a
        # file that cannot tell you its rate, which is worth None rather than a made-up 60.
        period_ms = _float_or_none(_attr(a, "ZAxisConversionConversionLinearScale"))
        rate = 1000.0 / period_ms if period_ms else None
        px = _float_or_none(_attr(a, "XAxisConversionConversionLinearScale"))
        return Unit(name=name, session=session, n_frames=int(n), height=int(h), width=int(w),
                    dtype=str(first.dtype), frame_rate_hz=rate,
                    pixel_size_um=px if px and px > 0 else None,
                    comment=_text(_attr(a, "Comment")), channels=channels)


def _unit_sort_key(name: str):
    digits = "".join(c for c in name if c.isdigit())
    return (int(digits) if digits else 0, name)
