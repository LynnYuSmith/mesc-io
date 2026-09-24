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

import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import h5py
import numpy as np

from .errors import MescIOError
from .values import ConversionWarning, to_reader_units

__all__ = ["MescFile", "Unit", "Channel", "MescError"]


class MescError(MescIOError, RuntimeError):
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
    #: False when the file gave no offset or scale for this channel and 0 / 1 stand in for them.
    #: Reading it "in reader units" then returns the stored integers unchanged, which is worth
    #: a warning: the −786 the reader removes is exactly what a missing attribute would keep.
    converted: bool = True

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
    #: Frames per second — only for a unit whose third axis is TIME. A z-stack's third axis
    #: is depth, and dividing 1000 by its step gave "1000 Hz" for a 1 µm slice spacing: a
    #: plausible number, in the right unit, that nothing in a pipeline would question.
    frame_rate_hz: Optional[float]
    pixel_size_um: Optional[float]
    comment: str
    channels: List[Channel]
    #: Slice spacing in µm — set instead of ``frame_rate_hz`` when the third axis is depth.
    z_step_um: Optional[float] = None
    #: The y pixel size, when it differs from x. Femtonics writes the two axes separately and
    #: they are not always equal: on a 408x512 frame of the 2026-09-24 calibration set, x is
    #: 0.126171875 µm against y 0.12629686820504823. ``pixel_size_um`` keeps x, as every caller
    #: already expects; this is here so anisotropy is visible rather than silently dropped.
    pixel_size_y_um: Optional[float] = None
    #: The microscope STAGE position (VirtX/VirtY/VirtZ, µm) — where the objective physically
    #: was. Not the injection-relative numbers people type into comments, and not
    #: ``GeomTransTransl``, whose x and y are zero. None when the file does not carry it.
    stage_um: Optional[Dict[str, float]] = None
    #: The same position "from the zero level" — ``AttributeRelativePosition`` SlowX/SlowY/SlowZ
    #: (Femtonics names the x stage axis ``TableY`` and vice versa; the Slow* ids are the ones
    #: that match what is typed). This is the number the software shows after "set zero", and
    #: the one the comments' ``x-180 y120 z-20 from a1`` refer to. The zero is set by hand on the
    #: rig, per axis, at any time — so it is only comparable within one zero-setting.
    stage_rel_um: Optional[Dict[str, float]] = None

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
        """One unit by its full `MSession_0/MUnit_3` path, or by `MUnit_3` when that is
        unambiguous.

        Most files hold a single session and the short name is fine. A file with more than one
        can hold two units of the same name, and returning the first would be handing back the
        wrong recording without saying so — so an ambiguous short name raises and lists the
        paths to choose from.
        """
        units = self.units()
        for u in units:                                   # a full path always wins
            if name == u.path:
                return u
        matches = [u for u in units if name == u.name]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise MescError(
                f"{name!r} is ambiguous in {self.path.name} — it exists in "
                f"{len(matches)} sessions ({', '.join(u.path for u in matches)}). "
                f"Name the one you mean.")
        raise KeyError(f"{name!r} not in {self.path.name}")

    # -- pixels ------------------------------------------------------------
    def read(self, unit: str, channel: int = 0, frames=None, reader_units: bool = True,
             max_gb: Optional[float] = 4.0):
        """Frames of one channel. `frames` is a slice or index array; None means all.

        With `reader_units=True` (the default) the values are what the native Femtonics
        reader displays, as float64. With False you get the stored integers untouched.

        A recording is commonly several gigabytes and converting it produces float64, four
        times the size of the stored uint16. So a request that would not plausibly fit in
        memory is **refused** with the number it would have needed and the two ways round it
        — a frame range, or `iter_frames`. Pass `max_gb=None` to lift the guard when you know
        the machine can take it.
        """
        u = self.unit(unit)
        ch = self._channel(u, channel)
        ds = self._f[f"{u.path}/{ch.dataset}"]
        if max_gb is not None:
            self._check_size(ds, frames, reader_units, max_gb, f"{u.path}/{ch.name}")
        block = ds[:] if frames is None else ds[frames]
        if not reader_units:
            return block
        self._warn_unconverted(u, ch)
        return to_reader_units(block, offset=ch.offset, scale=ch.scale)

    def iter_frames(self, unit: str, channel: int = 0, block: int = 500,
                    reader_units: bool = True) -> Iterator[np.ndarray]:
        """Whole recording, `block` frames at a time — the way to touch a file bigger than RAM.

        Yields arrays of `(block, height, width)`, the last one short. The conversion is
        applied per block, so nothing larger than one block is ever materialised.
        """
        u = self.unit(unit)
        ch = self._channel(u, channel)
        ds = self._f[f"{u.path}/{ch.dataset}"]
        if block < 1:
            raise ValueError("block must be at least 1 frame")
        if reader_units:
            self._warn_unconverted(u, ch)
        for start in range(0, ds.shape[0], block):
            chunk = ds[start:start + block]
            yield (to_reader_units(chunk, offset=ch.offset, scale=ch.scale)
                   if reader_units else chunk)

    def _channel(self, u: "Unit", channel) -> Channel:
        try:
            return u.channels[channel] if isinstance(channel, int) else next(
                c for c in u.channels if c.name == channel)
        except (IndexError, StopIteration):
            raise KeyError(f"{u.path} has no channel {channel!r} "
                           f"(has {[c.name for c in u.channels]})") from None

    @staticmethod
    def _warn_unconverted(u: "Unit", ch: Channel) -> None:
        if not ch.converted:
            warnings.warn(
                f"{u.path}/{ch.name} states no ConversionLinearOffset/Scale — these 'reader units' "
                "are the stored integers unchanged, with the PMT offset still in them",
                ConversionWarning, stacklevel=3)

    @staticmethod
    def _check_size(ds, frames, reader_units, max_gb: float, what: str) -> None:
        n = ds.shape[0] if frames is None else len(range(*frames.indices(ds.shape[0]))) \
            if isinstance(frames, slice) else len(np.atleast_1d(frames))
        itemsize = 8 if reader_units else ds.dtype.itemsize
        gb = n * int(np.prod(ds.shape[1:])) * itemsize / 1e9
        if gb > max_gb:
            raise MemoryError(
                f"{what}: reading {n} frames "
                f"{'as float64 ' if reader_units else ''}needs about {gb:.1f} GB, over the "
                f"{max_gb:g} GB guard. Read a range (frames=slice(0, 1000)), stream it with "
                f"iter_frames(), or pass max_gb=None if this machine can take it.")

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
                                    scale=1.0 if sc is None else sc,
                                    converted=off is not None and sc is not None))
        first = grp[chan_names[0]]
        n, h, w = (first.shape + (0, 0, 0))[:3]
        # The third axis is TIME in a recording and DEPTH in a z-stack, and the file says
        # which: ``ZAxisGeomRole`` is 0 for time and 3 for depth, with the unit name ("ms" or
        # "µm") agreeing. Reading the scale without asking turned a 1 µm slice spacing into
        # "1000 Hz" on five of the nine units of the 2026-09-24 calibration set — a number that
        # is plausible, correctly typed, and would have gone into a rolling baseline and an
        # event window without a murmur. So the rate is only offered when the axis is time,
        # and the spacing only when it is depth.
        z_scale = _float_or_none(_attr(a, "ZAxisConversionConversionLinearScale"))
        rate = z_step = None
        if z_scale:
            if _z_axis_is_time(a):
                rate = 1000.0 / z_scale          # the scale is a frame PERIOD in ms
            else:
                z_step = z_scale                 # µm per slice
        px = _float_or_none(_attr(a, "XAxisConversionConversionLinearScale"))
        py = _float_or_none(_attr(a, "YAxisConversionConversionLinearScale"))
        return Unit(name=name, session=session, n_frames=int(n), height=int(h), width=int(w),
                    dtype=str(first.dtype), frame_rate_hz=rate, z_step_um=z_step,
                    pixel_size_um=px if px and px > 0 else None,
                    pixel_size_y_um=(py if py and py > 0 and px and abs(py - px) > 1e-9
                                     else None),
                    comment=_text(_attr(a, "Comment")), channels=channels,
                    stage_um=_stage_position(a),
                    stage_rel_um=_stage_position(a, "AttributeRelativePosition", "Slow"))


#: ``ZAxisGeomRole``: 0 is the time axis of a recording, 3 the depth axis of a z-stack.
Z_ROLE_TIME, Z_ROLE_DEPTH = 0, 3


def _z_axis_is_time(attrs) -> bool:
    """Is the third axis time, or depth?

    ``ZAxisGeomRole`` answers it outright. The unit name is the fallback for a file that omits
    the role: "ms" or "s" is time, "µm" is depth. When neither says anything, time is assumed,
    because every recording this reader was written for is one.
    """
    role = _float_or_none(_attr(attrs, "ZAxisGeomRole"))
    if role is not None:
        return int(role) != Z_ROLE_DEPTH
    name = _text(_attr(attrs, "ZAxisConversionUnitName")).strip().lower()
    if name in ("ms", "s", "us", "µs"):
        return True
    if "m" == name.replace("µ", "").replace("u", "").strip():
        return False
    return True


def _stage_position(attrs, attribute: str = "AttributePosition", prefix: str = "Virt") -> Optional[Dict[str, float]]:
    """``{prefix}X/Y/Z`` axes carrying ``attribute`` from ``MeasurementParamsXML``, or None.

    ``AttributePosition`` + ``Virt`` is the absolute stage; ``AttributeRelativePosition`` +
    ``Slow`` is the position from the zero set on the rig. Decoded as latin-1: the block carries
    a µ sign that is not UTF-8. Anything unparseable is None rather than an exception — a viewer
    must open a file whose XML is odd.
    """
    xml = _attr(attrs, "MeasurementParamsXML")
    if xml is None:
        return None
    if isinstance(xml, (bytes, bytearray)):
        xml = bytes(xml).decode("latin-1", "replace")
    elif isinstance(xml, np.ndarray):
        xml = bytes(int(c) for c in xml.ravel() if 0 < int(c) < 256).decode("latin-1", "replace")
    try:
        root = ET.fromstring(str(xml).rstrip("\x00"))
    except ET.ParseError:
        return None
    ids = {prefix + "X", prefix + "Y", prefix + "Z"}
    out: Dict[str, float] = {}
    for ax in root.iter("axis"):
        if ax.get("attribute") == attribute and ax.get("id") in ids:
            try:
                out[ax.get("id")[-1].lower()] = float(ax.get("value"))
            except (TypeError, ValueError):
                pass
    return out or None


def _unit_sort_key(name: str):
    digits = "".join(c for c in name if c.isdigit())
    return (int(digits) if digits else 0, name)
