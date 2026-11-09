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

import os
import warnings
import xml.etree.ElementTree as ET
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterator, List, Optional, Tuple

import h5py
import numpy as np
from h5py._objects import phil as _phil

from .errors import MescIOError

_THREADS = max(1, min(8, (os.cpu_count() or 2)))


def _per_frame_gzip(ds) -> bool:
    """MESc's own layout: one chunk per frame, deflate and nothing else. Only then are the
    chunks read raw and inflated here; anything else goes through h5py untouched."""
    try:
        return (ds.chunks is not None and ds.ndim == 3 and ds.chunks == (1,) + ds.shape[1:]
                and ds.compression == "gzip" and not ds.shuffle and not ds.fletcher32
                and ds.scaleoffset is None and ds.dtype.byteorder in ("=", "<", "|"))
    except Exception:  # noqa: BLE001
        return False


def _frames(ds, idx) -> np.ndarray:
    """``ds[idx]`` for a list of frame indices — fast for MESc's one-chunk-per-frame gzip.

    h5py's own path spends most of its time outside zlib (5 s for 3,715 frames of 512² where
    the inflating is 2.6 s). Here each frame's chunk is read as stored bytes and inflated in a
    few threads — zlib lets go of the GIL — so the same frames come in under a second on a
    current laptop, byte-identical. A chunk that is not there (never written) or does not
    inflate falls back to h5py for that frame, so its error, or its fill value, is h5py's.
    """
    idx = list(idx)
    out = np.empty((len(idx),) + ds.shape[1:], dtype=ds.dtype)
    if not idx:
        return out
    n_bytes = int(np.prod(ds.shape[1:])) * ds.dtype.itemsize

    # the stored bytes are read one after another — HDF5 itself must never be entered from two
    # threads (it crashes) — and only the inflating, which is pure zlib, is spread over threads
    # h5py's own global lock: HDF5 is not thread-safe, and the viewer serves requests from
    # several threads — without it two requests reading raw chunks at once segfaulted inside
    # libhdf5 (7 crashes on 27 Oct 2026, the first day this path ran under the viewer)
    raws = []
    with _phil:
        for i in idx:
            try:
                raws.append(ds.id.read_direct_chunk((i,) + (0,) * (ds.ndim - 1))[1])
            except Exception:  # noqa: BLE001 — an unwritten chunk: h5py answers for it below
                raws.append(None)

    def one(k):
        if raws[k] is None:
            return k
        try:
            buf = zlib.decompress(raws[k])
            if len(buf) != n_bytes:
                return k
            out[k] = np.frombuffer(buf, dtype=ds.dtype).reshape(ds.shape[1:])
            return None
        except zlib.error:
            return k
    with ThreadPoolExecutor(_THREADS) as ex:
        bad = [k for k in ex.map(one, range(len(idx))) if k is not None]
    for k in bad:                        # h5py's answer — or h5py's error — for these frames
        out[k] = ds[idx[k]]
    return out


def _read(ds, frames):
    """``ds[frames]`` (frames None, a slice, or indices), by the fast path when the layout allows."""
    if not _per_frame_gzip(ds):
        return ds[:] if frames is None else ds[frames]
    n = ds.shape[0]
    if frames is None:
        return _frames(ds, range(n))
    if isinstance(frames, slice):
        return _frames(ds, range(n)[frames])
    if isinstance(frames, (int, np.integer)):
        return _frames(ds, [range(n)[frames]])[0]
    arr = np.asarray(frames)
    if arr.dtype == bool:
        return _frames(ds, np.flatnonzero(arr))
    return _frames(ds, [range(n)[int(i)] for i in arr.ravel()])
from .values import ConversionWarning, InvertWarning, to_reader_units

__all__ = ["MescFile", "Unit", "Channel", "MescError"]

if TYPE_CHECKING:                                   # the annotation only; imported lazily at call
    from .rig_rois import RigRoi


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
    #: The valid stored range ``(Channel_N_Conversion_LowerLimit…, …UpperLimit…)`` that MESc
    #: clamps the raw integers to before scaling. None when the file states none. Usually the
    #: whole uint16 range, which makes the clamp a no-op.
    limits: Optional[Tuple[float, float]] = None
    #: The PMT A/D inversion this channel was recorded with (``ad_invert`` of its detector in
    #: ``MeasurementParamsXML``; MESc ≥ 3.5.7). 1 is the tested case; 0 draws an
    #: `InvertWarning` on reads in reader units. None when the file does not say.
    ad_invert: Optional[int] = None

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
    #: A z-stack's depth, from its own geometry: slice ``i`` is at ``z0_um + i * z_step_um`` (µm,
    #: the rig's absolute z, larger = shallower), i.e. ``GeomTransTransl`` z plus the z axis's
    #: conversion offset — slice 0 is the DEEP end. The stage position above is one reading
    #: taken at some moment of the scan: on a 2026-10-27 file one tile's reading sat at the other
    #: end of its stack from its neighbours', 190 µm off, while their geometries agreed. None for
    #: a recording or a file without the geometry.
    z0_um: Optional[float] = None
    #: ``LabelingOriginTransl`` z: the zero the rig showed when the unit was taken (µm, absolute).
    #: Depths are given from it when every unit shares it; it moves when the zero is set again.
    z_origin_um: Optional[float] = None
    #: The unit as MESc's own information panel lists it, label by label and in its order
    #: (Item type, Date, Creator … Frame rate, Duration), each value worked out from the
    #: attributes the panel reads. ``()`` when the unit carries none of them.
    info: Tuple[Tuple[str, str], ...] = ()
    #: The A/D depth the unit was ACQUIRED at (``Params/BitCompression`` in
    #: ``MeasurementParamsXML``): 16, or 8 — then the uint16 container holds 8-bit samples
    #: shifted up by `sample_shift`, so a single frame has only a few dozen grey levels and the
    #: −786-style offset and any SNR read off it mislead. None when the file does not say.
    acquired_bits: Optional[int] = None
    #: The left shift applied to each sample before storage in that mode (the PMT's
    #: ``compression_shift_{8,16}bit``): single-frame values are multiples of ``2**sample_shift``.
    #: Averaged frames (a z-stack's FrameLoop) are not. None when the file does not say.
    sample_shift: Optional[int] = None
    #: The Pockels cell's on-intensity the unit was recorded with (``onintensity`` of the
    #: ``PockelsCell`` device in ``MeasurementParamsXML``) — the laser setting, in the cell's own
    #: units. Read from the file, not from what was typed into the comment (on our recordings the
    #: comment disagreed on 34 of 413 units). None when the file does not say.
    laser_pockels: Optional[float] = None
    #: Each PMT's reference voltage by channel name (``{"UG": 70.0, "UR": 70.0}``), from the
    #: ``PMT`` devices of ``MeasurementParamsXML``. None when the file carries no PMT block.
    pmt_reference_voltage: Optional[Dict[str, float]] = None
    #: ``Params/objective_name`` (e.g. "obj16x"). None when absent.
    objective: Optional[str] = None
    #: Every acquisition parameter of ``MeasurementParamsXML``, parsed and typed:
    #: ``{"task": str, "devices": {name: {param: value, "type": tag/type}}, "params": {name: value},
    #: "axes": {axis id: {attribute: value}}}``. Nothing is dropped; empty dicts when the XML is
    #: missing or unparseable.
    acquisition: Optional[Dict[str, object]] = None

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


def _conversion_limits(a, cn: str) -> Optional[Tuple[float, float]]:
    """The channel's raw clamp range. The Uint16 pair is the one in the stored integers' own
    terms; the Double pair (same values in every file seen) is the fallback."""
    for kind in ("Uint16", "Double"):
        lo = _float_or_none(_attr(a, f"{cn}_Conversion_LowerLimit{kind}"))
        hi = _float_or_none(_attr(a, f"{cn}_Conversion_UpperLimit{kind}"))
        if lo is not None and hi is not None:
            return (lo, hi)
    return None


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
        ds = self._dataset(u, ch)
        if max_gb is not None:
            self._check_size(ds, frames, reader_units, max_gb, f"{u.path}/{ch.name}")
        block = _read(ds, frames)
        if not reader_units:
            return block
        self._warn_unconverted(u, ch)
        self._warn_invert(u, ch)
        return to_reader_units(block, offset=ch.offset, scale=ch.scale, limits=ch.limits)

    def iter_frames(self, unit: str, channel: int = 0, block: int = 500,
                    reader_units: bool = True) -> Iterator[np.ndarray]:
        """Whole recording, `block` frames at a time — the way to touch a file bigger than RAM.

        Yields arrays of `(block, height, width)`, the last one short. The conversion is
        applied per block, so nothing larger than one block is ever materialised.
        """
        u = self.unit(unit)
        ch = self._channel(u, channel)
        ds = self._dataset(u, ch)
        if block < 1:
            raise ValueError("block must be at least 1 frame")
        if reader_units:
            self._warn_unconverted(u, ch)
            self._warn_invert(u, ch)
        for start in range(0, ds.shape[0], block):
            chunk = _read(ds, slice(start, start + block))
            yield (to_reader_units(chunk, offset=ch.offset, scale=ch.scale, limits=ch.limits)
                   if reader_units else chunk)

    def frame_times(self, unit: str, channel: int = 0) -> Optional[np.ndarray]:
        """The hardware time stamp at the END of each frame, in seconds from the start of the unit.

        MESc records one stamp per frame and channel in ``Curve_N/CurveDataYRawData`` (a curve
        named after the channel, ``Comment = "INPUT;TIMESTAMP"``), in ticks of the acquisition
        clock that the curve's own Y conversion turns into milliseconds (2e-5 ms a tick on the
        files tested, i.e. a 50 MHz clock). The first stamp is about one frame period: it closes
        frame 0. A curve one sample longer than the movie ends with an end-of-acquisition stamp,
        which is dropped.

        These are the real times. The nominal period (``frame_rate_hz``) leaves out any pause in
        the acquisition — on the files tested, most recordings pause ≈0.6 s after the first few
        dark frames — and runs about 0.04 % slow. `frame_stalls` finds the pauses.

        Returns float64 of length ``n_frames``, or None when the unit has no stamps (z-stacks keep
        an empty curve) or the file has no curves. A curve shorter than the movie (an aborted
        recording) is returned as it is, with a warning.
        """
        u = self.unit(unit)
        ch = self._channel(u, channel)
        try:
            grp = self._f[u.path]
        except KeyError:
            return None
        curves = sorted((k for k in grp if k.startswith("Curve_")), key=_unit_sort_key)
        want = _text(_attr(grp.attrs, f"{ch.name}_Name"))
        # an unnamed channel matches by position only: "" == "" would hand every channel curve 0
        named = [c for c in curves if want and _text(_attr(grp[c].attrs, "Name")) == want]
        name = named[0] if named else (curves[ch.index] if ch.index < len(curves) else None)
        if name is None or "CurveDataYRawData" not in grp[name]:
            return None
        d = grp[name]["CurveDataYRawData"]
        if d.shape is None or not d.size:
            return None
        ca = grp[name].attrs
        scale = _float_or_none(_attr(ca, "CurveDataYConversionConversionLinearScale")) or 1.0
        offset = _float_or_none(_attr(ca, "CurveDataYConversionConversionLinearOffset")) or 0.0
        t = (np.asarray(d[:], dtype=np.float64).ravel() * scale + offset) / 1000.0
        if len(t) >= u.n_frames:
            return t[:u.n_frames]
        warnings.warn(f"{u.path}/{name} holds {len(t)} stamps for {u.n_frames} frames — returned "
                      "as they are", RuntimeWarning, stacklevel=2)
        return t

    def rig_rois(self, unit: str) -> List["RigRoi"]:
        """The ROIs drawn on this unit in MESc on the rig (saved in ``ViewerParamsXML``), with
        their vertices in µm and in pixels. ``[]`` when none were saved. See `mesc_io.rig_rois`."""
        from .rig_rois import decode_rig_rois
        u = self.unit(unit)
        try:
            a = self._f[u.path].attrs
        except KeyError:
            return []
        axes = []
        for ax in "XY":
            off = _float_or_none(_attr(a, f"{ax}AxisConversionConversionLinearOffset"))
            sc = _float_or_none(_attr(a, f"{ax}AxisConversionConversionLinearScale"))
            axes.append((off, sc) if off is not None and sc else None)
        return decode_rig_rois(_attr(a, "ViewerParamsXML"), axes[0], axes[1], where=u.path)

    def frame_stalls(self, unit: str, channel: int = 0, factor: float = 3.0) -> List[Tuple[int, float]]:
        """Pauses in the acquisition: ``[(frame, seconds), ...]`` for every frame whose interval
        to the previous stamp exceeds `factor` × the median interval. ``frame`` is the first
        frame whose stamp came late (the pause falls before or inside it: on the files tested,
        frame 8, the last dark frame), ``seconds`` the time lost (interval − median). Empty when the
        stamps are regular or absent."""
        t = self.frame_times(unit, channel)
        if t is None or len(t) < 3:
            return []
        dt = np.diff(t)
        med = float(np.median(dt))
        return [(int(i) + 1, float(dt[i] - med)) for i in np.flatnonzero(dt > factor * med)]

    def _dataset(self, u: "Unit", ch: Channel):
        """The stored frames of one channel. A recording that keeps its frames elsewhere (another
        HDF5 layout: a pipeline's master file) subclasses MescFile and overrides this and
        ``units()``; read, iter_frames, the conversion and the size guard are then inherited."""
        return self._f[f"{u.path}/{ch.dataset}"]

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
    def _warn_invert(u: "Unit", ch: Channel) -> None:
        if ch.ad_invert == 0:
            warnings.warn(
                f"{u.path}/{ch.name} was recorded with ad_invert = 0 (PMT inversion off). mesc-io "
                "is tested on ad_invert = 1 only: these reader units have not been checked against "
                "MESc and may be inverted or offset. The stored integers (reader_units=False) are "
                "exact.", InvertWarning, stacklevel=3)

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
        xml = _measurement_xml(a)              # parsed once, read by the helpers below
        inverts = _pmt_ad_invert(xml) if xml is not None else {}
        channels = []
        for i, cn in enumerate(chan_names):
            off = _float_or_none(_attr(a, f"{cn}_Conversion_ConversionLinearOffset"))
            sc = _float_or_none(_attr(a, f"{cn}_Conversion_ConversionLinearScale"))
            channels.append(Channel(index=i, name=cn,
                                    offset=0.0 if off is None else off,
                                    scale=1.0 if sc is None else sc,
                                    converted=off is not None and sc is not None,
                                    lut=_lut_bounds(_attr(a, f"{cn}_LUT_VecBounds")),
                                    colour=_lut_colour(_attr(a, f"{cn}_LUT_VecColors")),
                                    limits=_conversion_limits(a, cn),
                                    ad_invert=inverts.get(_text(_attr(a, f"{cn}_Name")))))
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
        z0 = z_origin = None
        if z_step:
            g, zoff = _vec(a, "GeomTransTransl", 3), _float_or_none(_attr(a, "ZAxisConversionConversionLinearOffset"))
            # both or neither: without the axis offset the translation is the stack's centre, and
            # taking it for slice 0 would put every slice half a stack off
            if g is not None and np.isfinite(g[2]) and zoff is not None:
                z0 = float(g[2]) + zoff
            o = _vec(a, "LabelingOriginTransl", 3)
            z_origin = float(o[2]) if o is not None and np.isfinite(o[2]) else None
        acq = _acquisition(xml)
        stage_abs = _stage_position(xml) if xml is not None else None
        stage_rel = _stage_position(xml, "AttributeRelativePosition", "Slow") if xml is not None else None
        bits = _acquisition_bits(xml) if xml is not None else (None, None)
        return Unit(name=name, session=session, n_frames=int(n), height=int(h), width=int(w),
                    dtype=str(first.dtype), frame_rate_hz=rate, z_step_um=z_step,
                    pixel_size_um=px if px and px > 0 else None,
                    pixel_size_y_um=(py if py and py > 0 and px and abs(py - px) > 1e-9
                                     else None),
                    comment=_text(_attr(a, "Comment")), channels=channels,
                    stage_um=stage_abs, stage_rel_um=stage_rel,
                    z0_um=z0, z_origin_um=z_origin,
                    info=_mesc_info(grp, chan_names, z_step) + _acquisition_rows(acq, stage_abs, stage_rel, bits[0]),
                    acquired_bits=bits[0], sample_shift=bits[1],
                    laser_pockels=_pockels_onintensity(acq), pmt_reference_voltage=_pmt_voltages(acq),
                    objective=(str(acq["params"]["objective_name"]) if "objective_name" in acq["params"] else None),
                    acquisition=acq)


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
    root = _xml_root(attrs)
    if root is None:
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


def _xml_root(attrs_or_root):
    """Accept a unit's attributes or an already parsed ``MeasurementParamsXML`` root, so one unit
    is parsed once however many helpers read it."""
    if isinstance(attrs_or_root, ET.Element):
        return attrs_or_root
    return _measurement_xml(attrs_or_root)


def _measurement_xml(attrs):
    """The parsed ``MeasurementParamsXML`` of a unit, or None when absent or unparseable.
    Decoded as latin-1: the block carries a µ sign that is not UTF-8."""
    xml = _attr(attrs, "MeasurementParamsXML")
    if xml is None:
        return None
    if isinstance(xml, (bytes, bytearray)):
        xml = bytes(xml).decode("latin-1", "replace")
    elif isinstance(xml, np.ndarray):
        xml = (xml.ravel()[0] if xml.dtype.kind == "O" else
               bytes(int(c) for c in xml.ravel() if 0 < int(c) < 256))
        if isinstance(xml, (bytes, bytearray)):
            xml = bytes(xml).decode("latin-1", "replace")
    try:
        return ET.fromstring(str(xml).rstrip("\x00"))
    except ET.ParseError:
        return None


def _pmt_ad_invert(attrs) -> Dict[str, int]:
    """``{channel_name: ad_invert}`` from the PMT ``Gear`` blocks of ``MeasurementParamsXML``
    (``<param name="channel_name" value="UG"/> <param name="ad_invert" value="1"/>``)."""
    root = _xml_root(attrs)
    out: Dict[str, int] = {}
    if root is None:
        return out
    for gear in root.iter("Gear"):
        p = {e.get("name"): e.get("value") for e in gear.iter("param")}
        if p.get("channel_name") and p.get("ad_invert") is not None:
            try:
                out[p["channel_name"]] = int(float(p["ad_invert"]))
            except ValueError:
                pass
    return out


def _acquisition_bits(attrs) -> Tuple[Optional[int], Optional[int]]:
    """``(BitCompression, compression_shift_<bits>bit)`` from ``MeasurementParamsXML``."""
    root = _xml_root(attrs)
    if root is None:
        return None, None
    bits = shift = None
    for p in root.iter("param"):
        if p.get("name") == "BitCompression":
            try:
                bits = int(float(p.get("value")))
            except (TypeError, ValueError):
                pass
            break
    if bits is not None:
        for gear in root.iter("Gear"):
            v = {e.get("name"): e.get("value") for e in gear.iter("param")}.get(f"compression_shift_{bits}bit")
            if v is not None:
                try:
                    shift = int(float(v))
                except ValueError:
                    continue
                break
    return bits, shift


def _xml_value(s: Optional[str]):
    """An XML value typed: int for an integer literal, float when it parses, else the text."""
    if s is None:
        return ""
    try:
        f = float(s)
    except ValueError:
        return s
    return int(f) if s.strip().lstrip("-").isdigit() else f


def _acquisition(attrs_or_root) -> Dict[str, object]:
    """Every parameter of ``MeasurementParamsXML``: devices (each ``<param>`` of each element under
    ``Devices``, plus its tag/type), ``Params``, and every attribute of every stage axis."""
    out: Dict[str, object] = {"task": "", "devices": {}, "params": {}, "axes": {}}
    root = _xml_root(attrs_or_root) if attrs_or_root is not None else None
    if root is None:
        return out
    out["task"] = root.get("Type", "")
    devices = root.find("Devices")
    for dev in (devices if devices is not None else []):
        d = {"type": dev.tag + (f"/{dev.get('type')}" if dev.get("type") else "")}
        for p in dev.iter("param"):
            d[p.get("name")] = _xml_value(p.get("value"))
        out["devices"][dev.get("name") or dev.tag] = d
    params = root.find("Params")
    for p in (params.iter("param") if params is not None else []):
        out["params"][p.get("name")] = _xml_value(p.get("value"))
    for ax in root.iter("axis"):
        if ax.get("id") and ax.get("attribute"):
            out["axes"].setdefault(ax.get("id"), {})[ax.get("attribute")] = _xml_value(ax.get("value"))
    return out


def _pockels_onintensity(acq: Dict[str, object]) -> Optional[float]:
    for name, d in acq.get("devices", {}).items():
        if "pockels" in (name + str(d.get("type", ""))).lower() and isinstance(d.get("onintensity"), (int, float)):
            return float(d["onintensity"])
    return None


def _pmt_voltages(acq: Dict[str, object]) -> Optional[Dict[str, float]]:
    out = {str(d["channel_name"]): float(d["reference_voltage"]) for d in acq.get("devices", {}).values()
           if "PMT" in str(d.get("type", "")) and d.get("channel_name")
           and isinstance(d.get("reference_voltage"), (int, float))}
    return out or None


def _acquisition_rows(acq, stage_abs, stage_rel, bits) -> Tuple[Tuple[str, str], ...]:
    """Rows this reader adds to the information panel — its own words, not MESc's: where the stage
    was (absolute, and from the zero set on the rig), and the laser and detector settings. MESc's
    "Centroid in absolute coordinates" above has x and y from ``GeomTransTransl``, which are always
    0 in these files; the stage x, y live only in the XML (``Virt*`` absolute, ``Slow*`` relative)."""
    rows: List[Tuple[str, str]] = []
    xyz = lambda d: ", ".join(f"{k} = {_num_text(d[k], 6)} µm" for k in "xyz" if k in d)
    if stage_abs:
        rows.append(("Stage position (absolute)", xyz(stage_abs)))
    if stage_rel:
        rows.append(("Stage position from the zero level", xyz(stage_rel)))
    if "objective_name" in acq.get("params", {}):
        rows.append(("Objective", str(acq["params"]["objective_name"])))
    pk = _pockels_onintensity(acq)
    if pk is not None:
        rows.append(("Pockels cell (on-intensity)", _num_text(round(pk, 2))))
    pmt = _pmt_voltages(acq)
    if pmt:
        rows.append(("PMT reference voltage", ", ".join(f"{k} {_num_text(v)}" for k, v in pmt.items())))
    if bits:
        rows.append(("Acquired bits", str(bits)))
    return tuple(rows)


def _unit_sort_key(name: str):
    digits = "".join(c for c in name if c.isdigit())
    return (int(digits) if digits else 0, name)
