#!/usr/bin/env python3
"""Write a small synthetic `.mesc` with something worth looking at, for trying the viewer.

    python tools/make_synthetic.py [out.mesc]        # default: synthetic_view.mesc
    mesc-io view synthetic_view.mesc

Three units — 1500, 400 and 900 frames at ~62 Hz, 128×128 px — over a dim wide blob, with
four bright spots: three that blink with different periods and one that never does. The
comments look like ours ("area1 4c4s 135deg"), the stage position is in the XML the way
Femtonics writes it, and the PMT offset is −786 so reader units come out as they do on a
real file. Nothing in it is data; it exists so the viewer can be tried on a machine that
has no recording on it.
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


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "synthetic_view.mesc")))
