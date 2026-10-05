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
from typing import Dict, Iterator, List, Optional, Tuple

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
        if value.dtype.kind in "SUO":                  # an array of strings (TypeDebugString is one)
            return " ".join(_text(v) for v in value.ravel()).strip()
        return "".join(chr(int(c)) for c in value.ravel() if int(c)).strip()
    if isinstance(value, np.bytes_):
        return bytes(value).decode("utf-8", "replace").rstrip("\x00").strip()
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
    #: The display window the acquisition software saved for this channel
    #: (``Channel_N_LUT_VecBounds``), in reader units: what the recording looked like on the rig.
    #: None when the file carries no LUT.
    lut: Optional[Tuple[float, float]] = None
    #: The channel's display colour from the same LUT (``Channel_N_LUT_VecColors``, the top
    #: colour as 0xRRGGBB), e.g. "#00ff00" for green. None when absent or black.
    colour: Optional[str] = None

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
    #: The unit as MESc's own information panel lists it, label by label and in its order
    #: (Item type, Date, Creator … Frame rate, Duration), each value worked out from the
    #: attributes the panel reads. ``()`` when the unit carries none of them.
    info: Tuple[Tuple[str, str], ...] = ()

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


def _lut_bounds(value) -> Optional[Tuple[float, float]]:
    """``[lo, …, hi]`` LUT breakpoints -> (lo, hi), or None when absent or not a usable window."""
    if value is None:
        return None
    try:
        v = np.asarray(value, dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    v = v[np.isfinite(v)]
    if v.size < 2 or not v.max() > v.min():
        return None
    return float(v.min()), float(v.max())


def _lut_colour(value) -> Optional[str]:
    """``[…, 0xRRGGBB]`` LUT colours -> "#rrggbb" of the brightest end, or None."""
    if value is None:
        return None
    try:
        v = np.asarray(value).ravel()
        top = int(v[-1])
    except (TypeError, ValueError, IndexError):
        return None
    if not 0 < top <= 0xFFFFFF:
        return None
    return f"#{top:06x}"


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
                                    converted=off is not None and sc is not None,
                                    lut=_lut_bounds(_attr(a, f"{cn}_LUT_VecBounds")),
                                    colour=_lut_colour(_attr(a, f"{cn}_LUT_VecColors"))))
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
                    stage_rel_um=_stage_position(a, "AttributeRelativePosition", "Slow"),
                    info=_mesc_info(grp, chan_names, z_step))


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


def _num_text(v: float, digits: int = 6) -> str:
    """A number as MESc prints it: up to ``digits`` significant figures, no trailing zeros, no -0."""
    t = f"{v:.{digits}g}"
    if "e" in t:
        t = f"{v:.{max(0, digits - 1)}f}".rstrip("0").rstrip(".")
    return "0" if t in ("-0", "0", "") else t


def _vec(attrs, name, n=3):
    v = _attr(attrs, name)
    try:
        a = np.asarray(v, dtype=float).ravel()
        return a if a.size >= n and np.all(np.isfinite(a[:n])) else None
    except (TypeError, ValueError):
        return None


def _euler_zxy_deg(q) -> Tuple[float, float, float]:
    """``GeomTransRot`` (a quaternion, x y z w) as MESc's "Rotation (ZX'Y" Euler angles)": the
    intrinsic z, then x', then y'' angles of R = Rz(a)·Rx(b)·Ry(c), in degrees."""
    x, y, z, w = (float(c) for c in q[:4])
    n = (x * x + y * y + z * z + w * w) ** .5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    r01 = 2 * (x * y - z * w); r11 = 1 - 2 * (x * x + z * z); r21 = 2 * (y * z + x * w)
    r20 = 2 * (x * z - y * w); r22 = 1 - 2 * (x * x + y * y)
    b = np.degrees(np.arcsin(max(-1.0, min(1.0, r21))))
    a = np.degrees(np.arctan2(-r01, r11)); c = np.degrees(np.arctan2(-r20, r22))
    return tuple(0.0 if abs(t) < 5e-7 else float(t) for t in (a, b, c))


def _gib(nbytes: int) -> str:
    for unit, k in (("GiB", 2 ** 30), ("MiB", 2 ** 20), ("KiB", 2 ** 10)):
        if nbytes >= k:
            return f"{nbytes / k:.1f} {unit}"
    return f"{nbytes} B"


def _duration_text(s: float) -> str:
    """"1 min 20 s" — MESc's way, rounded to the second."""
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    parts = ([f"{h} h"] if h else []) + ([f"{m} min"] if m else []) + ([f"{sec} s"] if sec or not (h or m) else [])
    return " ".join(parts)


def _mesc_info(grp, chan_names, z_step) -> Tuple[Tuple[str, str], ...]:
    """The rows of MESc's information panel for one unit, from the attributes behind them.

    Every value is worked out, not copied from a cache of the panel (there is none in the file):
    the centroid is ``GeomTransTransl`` plus the middle of the field along x and y (each axis's
    conversion offset + its middle pixel centre), "from the zero level" is that minus
    ``LabelingOriginTransl``, the rotation is the ``GeomTransRot`` quaternion as Z-X'-Y'' Euler
    angles, the size is the channels' bytes on disk. Compared with a photo of the panel on the rig
    (2026-10-05, a 256 × 256 × 4953 time series of the same setup): type, creator, revision,
    profile, user, host, setup, signals, measurement type, dimensions, channels, size, bits, pixel
    size, scanning area, x/y centroid, rotation, frame rate and duration agree in value and form.
    The z centroid could not be compared (that unit is not in the files here), and neither could
    any row of a z-stack: its centroid is given at the stage's z, as for a recording, and its
    "Measurement type", "Slice step" and "Depth" are this reader's words, not MESc's.
    Anything the file does not carry is left out rather than guessed.
    """
    a = grp.attrs
    rows: List[Tuple[str, str]] = []
    add = lambda k, v: rows.append((k, v)) if v not in (None, "") else None
    t = _text(_attr(a, "TypeDebugString"))
    add("Item type", "Measurement" if t == "MImage3D" else t)
    sec, ns = _float_or_none(_attr(a, "MeasurementDatePosix")), _float_or_none(_attr(a, "MeasurementDateNanoSecs"))
    if sec:
        import datetime as _dt
        d = _dt.datetime.fromtimestamp(sec + (ns or 0) / 1e9)          # local time, as the rig shows it
        add("Date", d.strftime("%Y-%m-%d %H:%M:%S.") + f"{d.microsecond // 1000:03d}")
    add("Creator", _text(_attr(a, "CreatingMEScVersion")))
    rev = _float_or_none(_attr(a, "CreatingMEScRevision"))
    add("Creator revision", f"{int(rev)}" if rev is not None else None)
    add("Profile name", _text(_attr(a, "ExperimenterProfilename")))
    add("User name", _text(_attr(a, "ExperimenterUsername")))
    add("Host name", _text(_attr(a, "ExperimenterHostname")))
    add("Setup name", _text(_attr(a, "ExperimenterSetupID")))
    curves = [_text(_attr(grp[c].attrs, "Name")) for c in sorted(k for k in grp if k.startswith("Curve_"))]
    add("Recorded I/O signals", ", ".join(c for c in curves if c))
    xml = _attr(a, "MeasurementParamsXML")
    if isinstance(xml, np.ndarray):
        xml = xml.ravel()[0] if xml.dtype.kind == "O" else bytes(int(c) for c in xml.ravel() if 0 < int(c) < 256)
    task = ""
    if isinstance(xml, (bytes, bytearray)):
        import re as _re
        m = _re.search(rb'<Task Type="([^"]*)"', bytes(xml))
        task = m.group(1).decode("latin-1") if m else ""
    kind = "Resonant" if "Resonant" in task else ("Galvo" if "Galvo" in task else "")
    add("Measurement type", (f"{kind} XY scan " if kind else "XY scan ") + ("z-stack" if z_step else "time series"))
    xd, yd, zd = (_float_or_none(_attr(a, k)) for k in ("XDim", "YDim", "ZDim"))
    if xd and yd and zd:
        add("Dimensions", f"{int(xd)} × {int(yd)} × {int(zd)}")
    names = [_text(_attr(a, f"{c}_Name")) or c for c in chan_names]
    add("Channels", ", ".join(names))
    dsets = [grp[c] for c in chan_names]
    add("Size", _gib(sum(int(d.size) * d.dtype.itemsize for d in dsets)))
    add("Bits per sample", f"{dsets[0].dtype.itemsize * 8}" if dsets else None)
    px, py = (_float_or_none(_attr(a, f"{ax}AxisConversionConversionLinearScale")) for ax in "XY")
    if px and py:
        add("Pixel size", f"{_num_text(px)} µm × {_num_text(py)} µm")
        if xd and yd:
            add("Scanning area", f"{_num_text(px * xd)} µm × {_num_text(py * yd)} µm")
    tr = _vec(a, "GeomTransTransl")
    if tr is not None:
        ox, oy = (_float_or_none(_attr(a, f"{ax}AxisConversionConversionLinearOffset")) for ax in "XY")
        # the middle of the field is the middle PIXEL CENTRE: offset + (n-1)/2 steps (MESc: x = 0 for
        # an offset of -57.2625 on 256 px of 0.449118 µm, which (n-1)/2 gives and n/2 misses by 0.22)
        cx = tr[0] + (ox + px * (xd - 1) / 2 if ox is not None and px and xd else 0)
        cy = tr[1] + (oy + py * (yd - 1) / 2 if oy is not None and py and yd else 0)
        c = (cx, cy, tr[2])
        fmt = lambda v: _num_text(v, 6)                  # MESc: six significant figures, "-26967", "-20.24"
        add("Centroid in absolute coordinates", ", ".join(f"{k} = {fmt(v)} µm" for k, v in zip("xyz", c)))
        lo = _vec(a, "LabelingOriginTransl")
        if lo is not None:
            add("Centroid from the zero level", ", ".join(f"{k} = {fmt(v - o)} µm" for k, v, o in zip("xyz", c, lo)))
    q = _vec(a, "GeomTransRot", 4)
    if q is not None:
        add("Rotation (ZX'Y\" Euler angles)", ", ".join(f"{_num_text(round(t, 4))}°" for t in _euler_zxy_deg(q)))
    zs = _float_or_none(_attr(a, "ZAxisConversionConversionLinearScale"))
    if zs and not z_step:
        add("Frame rate", f"{_num_text(1000.0 / zs)} Hz")
        if zd:
            add("Duration", _duration_text(zd * zs / 1000.0))
    elif z_step:
        add("Slice step", f"{_num_text(z_step)} µm")
        if zd:
            add("Depth", f"{_num_text(z_step * zd)} µm")
    return tuple(rows)


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
