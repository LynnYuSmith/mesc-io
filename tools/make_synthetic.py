#!/usr/bin/env python3
"""Write a small synthetic `.mesc` with something worth looking at, for trying the viewer.

    python tools/make_synthetic.py [out.mesc]        # default: synthetic_view.mesc
    python tools/make_synthetic.py --stack [out.mesc]  # a two-channel z-stack: synthetic_stack.mesc
    mesc-io view synthetic_view.mesc

Three units — 1500, 400 and 900 frames at ~62 Hz, 128×128 px — over a dim wide blob, with
four bright spots: three that blink with different periods and one that never does. The
comments look like ours ("area1 4c4s 135deg"), the stage position is in the XML the way
Femtonics writes it, and the PMT offset is −786 so reader units come out as they do on a
real file. Nothing in it is data; it exists so the viewer can be tried on a machine that
has no recording on it.

``--stack`` writes a z-stack instead, for the 3D and XYZ views: 48 slices 1 µm apart, 128×128 px
of 0.5 µm, two channels. Channel_0 (green) holds three thin axons running down through the stack
with boutons on them; Channel_1 (red, ten times brighter, as a red channel often is) holds two
round cells, one of which sits on an axon's last bouton, so the overlay has a place where both
channels are bright. A short recording sits beside it, which has no volume to give.
"""
from __future__ import annotations

import sys
from pathlib import Path

import h5py
import numpy as np

XML = ('<?xml version="1.0"?><Params><AxisControl><snapshot>'
       '<axis attribute="AttributePosition" id="VirtX" value="915.0"/>'
       '<axis attribute="AttributePosition" id="VirtY" value="3671.0"/>'
       '<axis attribute="AttributePosition" id="VirtZ" value="-9.0"/>'
       '<axis attribute="AttributeRelativePosition" id="SlowX" value="80.0"/>'
       '<axis attribute="AttributeRelativePosition" id="SlowY" value="-1210.0"/>'
       '<axis attribute="AttributeRelativePosition" id="SlowZ" value="-9.0"/>'
       '</snapshot></AxisControl><param name="PixelSizeX" value="0.5"/></Params>').encode("latin-1")
UNITS = [(1500, "area1 4c4s 135deg"), (400, "area1 spont"), (900, "area2 8s 5rep 045deg")]
SPOTS = [(30, 40), (70, 60), (95, 90), (50, 100)]        # the fourth one never blinks


def text(s: str) -> np.ndarray:
    return np.frombuffer((s + "\0").encode(), dtype=np.uint8)


def main(out: Path) -> int:
    rng = np.random.default_rng(0)
    with h5py.File(out, "w") as f:
        sess = f.create_group("MSession_0")
        for j, (n, comment) in enumerate(UNITS):
            u = sess.create_group(f"MUnit_{j}")
            h = w = 128
            yy, xx = np.mgrid[0:h, 0:w]
            base = 900 + 60 * np.exp(-((xx - 64) ** 2 + (yy - 70) ** 2) / 900.0)
            frames = np.empty((n, h, w), dtype=np.uint16)
            for i in range(n):
                img = base + rng.normal(0, 25, (h, w))
                for k, (px, py) in enumerate(SPOTS):
                    blink = 300 * (np.sin(i / (40 + 20 * k)) > 0.85) if k < 3 else 0
                    img += (blink + 120) * np.exp(-((xx - px) ** 2 + (yy - py) ** 2) / 8.0)
                frames[i] = np.clip(img, 0, 65535)
            u.create_dataset("Channel_0", data=frames)
            u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = -786.0
            u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 0.5
            u.attrs["ZAxisConversionConversionLinearScale"] = 16.16
            u.attrs["XAxisConversionConversionLinearScale"] = 0.5
            u.attrs["YAxisConversionConversionLinearScale"] = 0.5
            u.attrs["Comment"] = text(comment)
            u.attrs["MeasurementParamsXML"] = np.frombuffer(XML, dtype=np.uint8)
    print(f"  {out}: {len(UNITS)} units, {sum(n for n, _ in UNITS)} frames")
    print(f"  mesc-io view {out}")
    return 0


def lut_colours(rgb: int) -> np.ndarray:
    return np.array([0, rgb], dtype=np.uint32)


def stack(out: Path) -> int:
    rng = np.random.default_rng(1)
    d, h, w = 48, 128, 128
    zz, yy, xx = np.mgrid[0:d, 0:h, 0:w].astype(np.float32)
    # three axons running down through the stack, each from (x0, y0) at the surface to (x1, y1)
    # at the bottom, with a bouton every 12 slices
    green = 900 + np.zeros((d, h, w), dtype=np.float32)
    bout = []
    for x0, y0, x1, y1 in [(20, 30, 100, 90), (110, 20, 40, 60), (30, 110, 90, 105)]:
        ax, ay = x0 + (x1 - x0) * zz / (d - 1), y0 + (y1 - y0) * zz / (d - 1)
        green += 400 * np.exp(-((xx - ax) ** 2 + (yy - ay) ** 2) / 4.0)
        for bz in (4, 16, 28, 40):
            bx, by = x0 + (x1 - x0) * bz / (d - 1), y0 + (y1 - y0) * bz / (d - 1)
            bout.append((bz, bx, by))
            green += 2000 * np.exp(-((xx - bx) ** 2 + (yy - by) ** 2) / 30.0 - (zz - bz) ** 2 / 1.5)
    # the cells: one away from the axons, one on the first axon's last bouton
    red = 9000 + np.zeros_like(green)
    for cz, cx, cy in [(16, 95, 30), bout[3]]:
        red += 15000 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / 40.0 - (zz - cz) ** 2 / 12.0)
    with h5py.File(out, "w") as f:
        sess = f.create_group("MSession_0")
        u = sess.create_group("MUnit_0")
        for k, (vol, colour) in enumerate([(green, 0x00FF00), (red, 0xFF0000)]):
            noisy = vol + rng.normal(0, 15 * (1 + 9 * k), vol.shape)
            u.create_dataset(f"Channel_{k}", data=np.clip(noisy, 0, 65535).astype(np.uint16))
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearOffset"] = -786.0
            u.attrs[f"Channel_{k}_Conversion_ConversionLinearScale"] = 0.5
            u.attrs[f"Channel_{k}_LUT_VecColors"] = lut_colours(colour)
        u.attrs["ZAxisGeomRole"] = 3
        u.attrs["ZAxisConversionConversionLinearScale"] = 1.0
        u.attrs["XAxisConversionConversionLinearScale"] = 0.5
        u.attrs["YAxisConversionConversionLinearScale"] = 0.5
        u.attrs["Comment"] = text("area1 zstack 48x1um")
        u.attrs["MeasurementParamsXML"] = np.frombuffer(XML, dtype=np.uint8)
        r = sess.create_group("MUnit_1")
        r.create_dataset("Channel_0", data=np.full((60, h, w), 900, dtype=np.uint16))
        r.attrs["ZAxisGeomRole"] = 0
        r.attrs["ZAxisConversionConversionLinearScale"] = 16.16
        r.attrs["XAxisConversionConversionLinearScale"] = 0.5
        r.attrs["Comment"] = text("area1 spont")
    print(f"  {out}: a {d}-slice two-channel stack and a 60-frame recording")
    print(f"  mesc-io view {out}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--stack"]:
        sys.exit(stack(Path(args[1] if len(args) > 1 else "synthetic_stack.mesc")))
    sys.exit(main(Path(args[0] if args else "synthetic_view.mesc")))
