"""The ROIs drawn on the rig, as MESc saved them with the unit.

MESc keeps its viewer's state for each unit in the ``ViewerParamsXML`` attribute. Despite the
name it is not XML: it is base64 of a Qt ``QDataStream`` (big-endian) holding a
``QMap<QString, QVariant>`` keyed by Qt signal names. Under ``ROI_sigUpdateROI(QString)`` sits
a second base64 ``QDataStream``: the ROI list. Each ROI is a 16-byte QUuid, the byte length of
its record, and a ``QMap<QString, QVariant>`` with ``label``, ``polygonF`` (vertices in µm, in
the unit's field coordinates — the frame of ``X/YAxisConversion``), ``color``, ``firstZPlane``
/ ``lastZPlane``, ``polyType``, ``roiRole``, ``visible`` and a few display settings.

Decoded here from the Qt serialisation format, which is public; nothing of MESc is used. Only
the QVariant types that ROI records carry are understood. The outer map is not walked: the ROI
key is found directly, so an unknown viewer setting elsewhere cannot hide the ROIs, and an ROI
whose record holds an unknown type is skipped by its stated length, with a warning, instead of
losing the ones after it.
"""
from __future__ import annotations

import base64
import binascii
import struct
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

__all__ = ["RigRoi", "decode_rig_rois", "RigRoiWarning"]

ROI_KEY = "ROI_sigUpdateROI(QString)"


class RigRoiWarning(UserWarning):
    """Part of a unit's saved ROI state could not be decoded and was skipped."""


@dataclass(frozen=True)
class RigRoi:
    """One ROI drawn in MESc on the rig."""
    label: str
    #: Vertices ``(N, 2)`` as ``[x, y]`` in µm, in the unit's field coordinates, as MESc stores
    #: them (a closed polygon repeats its first vertex at the end).
    polygon_um: np.ndarray
    #: The same vertices in pixels of the unit's frame, ``[x, y]``, with ``(0, 0)`` the CENTRE
    #: of the first pixel (add 0.5 for corner-based tools such as ImageJ). None when the unit
    #: states no axis conversion.
    polygon_px: Optional[np.ndarray]
    colour: Optional[str] = None
    first_z: Optional[int] = None
    last_z: Optional[int] = None
    poly_type: Optional[int] = None
    role: Optional[int] = None
    visible: Optional[bool] = None
    uuid: str = ""
    #: Every field of the record as decoded, for what the named ones leave out.
    raw: Dict[str, object] = field(default_factory=dict, repr=False, compare=False)


class _Q:
    """A cursor over big-endian ``QDataStream`` bytes."""

    def __init__(self, b: bytes):
        self.b, self.p = b, 0

    def take(self, n: int) -> bytes:
        if self.p + n > len(self.b):
            raise ValueError("ran past the end of the stream")
        v = self.b[self.p:self.p + n]
        self.p += n
        return v

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self.take(4))[0]

    def f64(self) -> float:
        return struct.unpack(">d", self.take(8))[0]

    def qstr(self) -> Optional[str]:
        n = self.u32()
        return None if n == 0xFFFFFFFF else self.take(n).decode("utf-16-be")

    def variant(self):
        t = self.u32()
        self.u8()                                       # the null flag: the value follows anyway
        if t == 1:                                     # bool
            return bool(self.u8())
        if t == 2:                                      # int
            return self.i32()
        if t == 3:                                      # uint
            return self.u32()
        if t == 4:                                      # qlonglong
            return struct.unpack(">q", self.take(8))[0]
        if t == 5:                                      # qulonglong
            return struct.unpack(">Q", self.take(8))[0]
        if t == 6:                                      # double
            return self.f64()
        if t == 10:                                     # QString
            return self.qstr()
        if t == 26:                                     # QPointF
            return (self.f64(), self.f64())
        if t == 30:                                     # QUuid
            return self.take(16).hex()
        if t == 67:                                     # QColor: spec, then a r g b pad (u16)
            self.u8()
            _a, r, g, b, _pad = struct.unpack(">5H", self.take(10))
            return f"#{r >> 8:02x}{g >> 8:02x}{b >> 8:02x}"
        if t == 86:                                     # QPolygonF
            n = self.u32()
            return [(self.f64(), self.f64()) for _ in range(n)]
        raise ValueError(f"QVariant type {t} is not one an ROI record uses")


def _b64(value) -> Optional[bytes]:
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        value = bytes(int(c) for c in value.ravel() if 0 < int(c) < 256) if value.dtype.kind in "iu" \
            else value.ravel()[0]
    if isinstance(value, str):
        value = value.encode("ascii", "ignore")
    try:
        return base64.b64decode(bytes(value).rstrip(b"\x00"), validate=False)
    except (binascii.Error, TypeError, ValueError):
        return None


def _roi_payload(viewer_params) -> Optional[bytes]:
    """The decoded ROI stream inside a unit's ``ViewerParamsXML``, or None when it has none."""
    raw = _b64(viewer_params)
    if not raw:
        return None
    key = ROI_KEY.encode("utf-16-be")
    i = raw.find(struct.pack(">I", len(key)) + key)
    if i < 0:
        return None
    q = _Q(raw)
    q.p = i + 4 + len(key)
    try:
        inner = q.variant()
    except ValueError:
        return None
    return _b64(inner) if inner else None


def decode_rig_rois(viewer_params, x_axis: Optional[Tuple[float, float]] = None,
                    y_axis: Optional[Tuple[float, float]] = None, where: str = "") -> List[RigRoi]:
    """The ROIs in one unit's ``ViewerParamsXML`` (its raw attribute value).

    ``x_axis`` / ``y_axis`` are the unit's ``(ConversionLinearOffset, ConversionLinearScale)``
    for X and Y; with them each ROI also gets its vertices in pixels. ``[]`` when the unit has
    no saved ROIs.
    """
    payload = _roi_payload(viewer_params)
    if not payload:
        return []
    q = _Q(payload)
    out: List[RigRoi] = []
    try:
        n = q.u32()
    except ValueError:
        return []
    for k in range(n):
        try:
            uuid = q.take(16).hex()
            size = q.u32()
        except ValueError:
            warnings.warn(f"{where}: the ROI list ends after {k} of {n} ROIs", RigRoiWarning,
                          stacklevel=2)
            break
        start = q.p
        try:
            m = q.u32()
            rec = {}
            for _ in range(m):
                name = q.qstr()
                rec[name] = q.variant()
        except ValueError as e:
            warnings.warn(f"{where}: ROI {k + 1} of {n} skipped ({e})", RigRoiWarning, stacklevel=2)
            rec = None
        q.p = start + size                     # the stated length, whatever the decoding did
        if rec is None:
            continue
        out.append(_roi(rec, uuid, x_axis, y_axis))
    # stored in no useful order; ``order`` is when each was drawn (ms since the epoch)
    return sorted(out, key=lambda r: (not isinstance(r.raw.get("order"), int), r.raw.get("order") or 0))


def _roi(rec: Dict[str, object], uuid: str, x_axis, y_axis) -> RigRoi:
    um = np.asarray(rec.get("polygonF") or [], dtype=np.float64).reshape(-1, 2)
    px = None
    if x_axis and y_axis and x_axis[1] and y_axis[1]:
        px = np.column_stack(((um[:, 0] - x_axis[0]) / x_axis[1], (um[:, 1] - y_axis[0]) / y_axis[1]))

    def _int(k):
        v = rec.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    vis = rec.get("visible")
    return RigRoi(label=str(rec.get("label") or ""), polygon_um=um, polygon_px=px,
                  colour=rec.get("color") if isinstance(rec.get("color"), str) else None,
                  first_z=_int("firstZPlane"), last_z=_int("lastZPlane"),
                  poly_type=_int("polyType"), role=_int("roiRole"),
                  visible=None if vis is None else bool(vis),
                  uuid=str(rec.get("uniqueID") or uuid), raw=rec)
