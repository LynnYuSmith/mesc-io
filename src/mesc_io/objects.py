"""Objects in a z-stack grown from a seed, on the recording's own values.

A click picks a seed; the object is the connected region around it (face neighbours) of voxels at
least ``frac`` of the way from the stack's background to the seed's peak, no further than ``r_um``
from the peak. Grown here, on the stored data at full resolution, the region does not depend on how
the stack is displayed: on the page's 8-bit window bytes the same seed gave 86 µm³ under one window
and 834 µm³ under another (a peak held at 255 lowered every threshold), and its means were of
clipped bytes (red team, 2026-10-28). Only numpy is needed.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

import numpy as np

#: The most voxels an object may take before the growth stops (and says so).
MAX_VOXELS = 2_000_000
#: The background: this low percentile of the channel, from a sample spread over the whole stack.
BG_PERCENTILE = 5.0


def background(mesc, unit: str, channel: int) -> float:
    """The channel's background in reader units: a low percentile of every 4th slice, row and column."""
    u = mesc.unit(unit)
    c = u.channels[channel]
    raw = mesc.read(unit, channel=channel, frames=list(range(0, u.n_frames, 4)), reader_units=False, max_gb=None)
    v = np.percentile(np.asarray(raw)[:, ::4, ::4], BG_PERCENTILE)
    return float(v) * float(c.scale) + float(c.offset)


def grow(mesc, unit: str, channel: int, seed: Sequence[int], frac: float, r_um: float,
         down: int = 1, bg: Optional[float] = None, max_voxels: int = MAX_VOXELS) -> Dict:
    """The object around ``seed`` (z, y, x, full-resolution voxels) in ``channel`` of a z-stack.

    The peak is the brightest of the seed's 3×3×3; a voxel belongs when it is ≥ ``bg + frac × (peak
    − bg)``, within ``r_um`` of the peak (µm, by the stack's pixel and slice sizes), and joined to
    the peak face to face. Returns the numbers in µm and reader units, and — for drawing on a page
    whose volume is block-reduced ``down`` times across — the region's voxels on that grid
    (``idx``: z·Hy·Wx + y·Wx + x, each once).
    """
    u = mesc.unit(unit)
    if not u.z_step_um:
        raise ValueError(f"{unit} is not a z-stack")
    if not (0.0 < frac < 1.0) or not (r_um > 0):
        raise ValueError("frac must be in (0, 1) and r_um above 0")
    D, H, W = u.n_frames, u.height, u.width
    px = float(u.pixel_size_um or 1.0)
    py = float(u.pixel_size_y_um or px)
    dz = abs(float(u.z_step_um))
    z, y, x = (int(round(v)) for v in seed)
    if not (0 <= z < D and 0 <= y < H and 0 <= x < W):
        raise ValueError(f"the seed {list(seed)} is outside the stack ({D}, {H}, {W})")
    c = u.channels[channel]
    sc, off = float(c.scale), float(c.offset)
    bg = background(mesc, unit, channel) if bg is None else float(bg)
    # the box the radius allows (around the seed, one voxel more for the 3×3×3 and the edge test)
    rz, ry, rx = math.ceil(r_um / dz) + 2, math.ceil(r_um / py) + 2, math.ceil(r_um / px) + 2
    z0, z1 = max(0, z - rz), min(D, z + rz + 1)
    y0, y1 = max(0, y - ry), min(H, y + ry + 1)
    x0, x1 = max(0, x - rx), min(W, x + rx + 1)
    raw = np.asarray(mesc.read(unit, channel=channel, frames=list(range(z0, z1)), reader_units=False, max_gb=None))
    vol = raw[:, y0:y1, x0:x1].astype(np.float64) * sc + off
    # the peak: the brightest of the seed's 3×3×3 (the seed itself on a tie)
    sz, sy, sx = z - z0, y - y0, x - x0
    best, pk = (sz, sy, sx), vol[sz, sy, sx]
    for a in range(max(0, sz - 1), min(vol.shape[0], sz + 2)):
        for b in range(max(0, sy - 1), min(vol.shape[1], sy + 2)):
            for d in range(max(0, sx - 1), min(vol.shape[2], sx + 2)):
                if vol[a, b, d] > pk:
                    pk, best = vol[a, b, d], (a, b, d)
    lim = bg + frac * (pk - bg)
    zz, yy, xx = np.ogrid[:vol.shape[0], :vol.shape[1], :vol.shape[2]]
    inside = ((zz - best[0]) * dz) ** 2 + ((yy - best[1]) * py) ** 2 + ((xx - best[2]) * px) ** 2 <= r_um * r_um
    bright = vol >= lim
    ok = bright & inside
    reg = np.zeros(vol.shape, bool)
    reg[best] = True
    capN = False
    while True:                                   # grow face to face until nothing joins
        nb = reg.copy()
        nb[1:] |= reg[:-1]; nb[:-1] |= reg[1:]
        nb[:, 1:] |= reg[:, :-1]; nb[:, :-1] |= reg[:, 1:]
        nb[:, :, 1:] |= reg[:, :, :-1]; nb[:, :, :-1] |= reg[:, :, 1:]
        nb &= ok
        if nb.sum() == reg.sum():
            break
        reg = nb
        if reg.sum() > max_voxels:
            capN = True
            break
    # stopped by the radius: a bright neighbour of the region lies outside it
    edge = reg.copy()
    edge[1:] |= reg[:-1]; edge[:-1] |= reg[1:]
    edge[:, 1:] |= reg[:, :-1]; edge[:, :-1] |= reg[:, 1:]
    edge[:, :, 1:] |= reg[:, :, :-1]; edge[:, :, :-1] |= reg[:, :, 1:]
    capR = bool((edge & bright & ~inside).any())
    iz, iy, ix = np.nonzero(reg)
    n = int(iz.size)
    fz, fy, fx = iz + z0, iy + y0, ix + x0                 # full-resolution voxels
    cen = [float(fz.mean()), float(fy.mean()), float(fx.mean())]
    means = []
    for ch in range(len(u.channels)):
        cc = u.channels[ch]
        r_ = raw if ch == channel else np.asarray(mesc.read(unit, channel=ch, frames=list(range(z0, z1)),
                                                             reader_units=False, max_gb=None))
        v = r_[:, y0:y1, x0:x1][reg].astype(np.float64) * float(cc.scale) + float(cc.offset)
        means.append({"ch": ch, "v": float(v.mean())})
    k = max(1, int(down))
    Hy, Wx = H // k, W // k
    keep = (fy // k < Hy) & (fx // k < Wx)
    idx = np.unique(fz[keep] * (Hy * Wx) + (fy[keep] // k) * Wx + fx[keep] // k)
    pz, pyy, pxx = (int(v) for v in (best[0] + z0, best[1] + y0, best[2] + x0))
    return {
        "n": n, "um3": n * px * py * dz,
        "centre_vox": cen, "centre_um": [cen[2] * px, cen[1] * py, cen[0] * dz], "slice": int(round(cen[0])),
        "extent_um": [float((fx.max() - fx.min() + 1) * px), float((fy.max() - fy.min() + 1) * py), float((fz.max() - fz.min() + 1) * dz)],
        "peak": float(pk), "background": float(bg), "threshold": float(lim), "peak_vox": [pz, pyy, pxx],
        "means": means, "reached_radius": capR, "stopped_at_max": capN,
        "down": k, "idx": idx.astype(np.int64).tolist(),
    }
