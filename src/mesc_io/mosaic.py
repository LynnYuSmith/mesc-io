"""Mosaics of z-stacks: tiles placed where the stage put them, corrected from their overlaps,
composed with hard seams, and cut out.

A big field is taken as a grid of z-stacks ("tiles"), each with the stage position it was asked
for. The stage is good to a few microns, and a living brain moves between tiles, so the tiles are
placed by the stage first and then corrected: each overlapping pair is matched in 3-D (x, y and the
slice), and one correction per tile is solved for by least squares over all pairs. What the pairs
still disagree on after the solve is the mosaic's error, reported pair by pair.

The layout is plain JSON, the same the viewer keeps with its view::

    {"tiles": {"MSession_0/MUnit_1": {"dx": 0.0, "dy": 0.0, "dz": 0, "hidden": false}, ...},
     "order": ["MSession_0/MUnit_1", ...], "seams": "nearest"}

``dx``, ``dy`` (µm) move a tile from its stage position; ``dz`` (slices) says which mosaic plane
its slice 0 is drawn at — its slice ``s`` is mosaic plane ``s + dz``. The stage's own z is not used:
a stack's slices are counted from where the stack began, which the overlaps measure better than the
stage reports it. Every mosaic pixel comes from ONE tile (hard seams, no blending, so nothing is
averaged that was never one place): with ``"nearest"`` the tile whose centre is nearest, with
``"order"`` the last in ``order`` that covers it. Only numpy is needed; a TIFF needs tifffile.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class Tile:
    path: str
    name: str
    comment: str
    depth: int
    height: int
    width: int
    px: float          # µm per pixel along x
    py: float          # µm per pixel along y
    dz: float          # µm per slice
    x_um: float        # the stage's position of the tile's centre (from the rig's zero when known)
    y_um: float


def tiles(mesc, paths=None) -> List[Tile]:
    """The file's z-stacks that carry a stage position, in file order (or the ``paths`` given)."""
    out = []
    for u in mesc.units():
        if paths is not None and u.path not in paths:
            continue
        pos = u.stage_rel_um or u.stage_um
        if not u.z_step_um or u.n_frames < 2 or not pos or "x" not in pos or "y" not in pos or not u.pixel_size_um:
            continue
        out.append(Tile(u.path, u.name, u.comment or "", u.n_frames, u.height, u.width,
                        float(u.pixel_size_um), float(u.pixel_size_y_um or u.pixel_size_um),
                        float(u.z_step_um), float(pos["x"]), float(pos["y"])))
    if paths is not None:
        out.sort(key=lambda t: list(paths).index(t.path))
    return out


def _round(v: float) -> int:
    """Half up, as the viewer's Math.round: Python's round() goes to the even neighbour at .5,
    and one pixel of difference would put a tile in another place on screen than in an export."""
    return int(np.floor(v + 0.5))


def _entry(layout, path) -> dict:
    e = ((layout or {}).get("tiles") or {}).get(path) or {}
    return {"dx": float(e.get("dx", 0.0)), "dy": float(e.get("dy", 0.0)),
            "dz": _round(float(e.get("dz", 0))), "hidden": bool(e.get("hidden", False))}


def geometry(ts: List[Tile], layout=None) -> dict:
    """Where every shown tile sits in the mosaic, in whole mosaic pixels (the first tile's pixel
    size; tiles of another pixel size are left out, with the reason). The viewer draws by the same
    rule — top-left = round((centre + correction − half the tile − origin) / pixel) — so the
    screen and an export put every pixel in the same place."""
    shown = [t for t in ts if not _entry(layout, t.path)["hidden"]]
    if not shown:
        raise ValueError("no tile to show")
    ref = shown[0]
    skipped = {t.path: "pixel size differs from the first tile's" for t in shown
               if abs(t.px - ref.px) > 1e-6 or abs(t.py - ref.py) > 1e-6 or abs(t.dz - ref.dz) > 1e-6}
    shown = [t for t in shown if t.path not in skipped]
    left = {t.path: t.x_um + _entry(layout, t.path)["dx"] - t.width * t.px / 2 for t in shown}
    top = {t.path: t.y_um + _entry(layout, t.path)["dy"] - t.height * t.py / 2 for t in shown}
    ox, oy = min(left.values()), min(top.values())
    place = {}
    for t in shown:
        e = _entry(layout, t.path)
        c0, r0 = _round((left[t.path] - ox) / ref.px), _round((top[t.path] - oy) / ref.py)
        place[t.path] = {"c0": c0, "r0": r0, "z0": e["dz"], "tile": t,
                         "cx": c0 + t.width / 2, "cy": r0 + t.height / 2}
    W = max(p["c0"] + p["tile"].width for p in place.values())
    H = max(p["r0"] + p["tile"].height for p in place.values())
    z0 = min(p["z0"] for p in place.values())
    z1 = max(p["z0"] + p["tile"].depth for p in place.values())
    order = [p for p in ((layout or {}).get("order") or []) if p in place]
    order += [t.path for t in shown if t.path not in order]
    return {"place": place, "width": W, "height": H, "planes": (z0, z1), "px": ref.px, "py": ref.py,
            "dz": ref.dz, "origin_um": (ox, oy), "order": order, "skipped": skipped,
            "seams": (layout or {}).get("seams", "nearest")}


def compose(mesc, ts: List[Tile], layout=None, channel: int = 0, planes=None, crop=None,
            reader_units: bool = True) -> np.ndarray:
    """Mosaic planes (n, H, W) as float32, NaN where no tile reaches. ``planes``: mosaic plane
    indices (default all); ``crop``: (x0, y0, x1, y1) in mosaic pixels."""
    g = geometry(ts, layout)
    z0, z1 = g["planes"]
    planes = list(range(z0, z1)) if planes is None else [int(p) for p in planes]
    x0, y0, x1, y1 = crop if crop is not None else (0, 0, g["width"], g["height"])
    x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(g["width"], int(x1)), min(g["height"], int(y1))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("the crop is empty")
    out = np.full((len(planes), y1 - y0, x1 - x0), np.nan, np.float32)
    best = np.full((len(planes), y1 - y0, x1 - x0), np.inf, np.float32)
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32) + 0.5
    for rank, path in enumerate(g["order"]):
        p = g["place"][path]
        t = p["tile"]
        # this tile's part of the crop
        a0, a1 = max(x0, p["c0"]), min(x1, p["c0"] + t.width)
        b0, b1 = max(y0, p["r0"]), min(y1, p["r0"] + t.height)
        if a1 <= a0 or b1 <= b0:
            continue
        want = [(i, q - p["z0"]) for i, q in enumerate(planes) if 0 <= q - p["z0"] < t.depth]
        if not want:
            continue
        sl = [s for _, s in want]
        a = np.asarray(mesc.read(path, channel=channel, frames=sl, reader_units=reader_units), np.float32)
        a = a[:, b0 - p["r0"]:b1 - p["r0"], a0 - p["c0"]:a1 - p["c0"]]
        if g["seams"] == "order":
            score = np.full((b1 - b0, a1 - a0), -float(rank), np.float32)
        else:
            score = (xx[b0 - y0:b1 - y0, a0 - x0:a1 - x0] - p["cx"]) ** 2 + (yy[b0 - y0:b1 - y0, a0 - x0:a1 - x0] - p["cy"]) ** 2
        for j, (i, _) in enumerate(want):
            o, bs = out[i, b0 - y0:b1 - y0, a0 - x0:a1 - x0], best[i, b0 - y0:b1 - y0, a0 - x0:a1 - x0]
            m = score < bs
            o[m] = a[j][m]
            bs[m] = score[m]
    return out


# -- stitching from the overlaps ------------------------------------------------------------------

def _smooth(a: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur over the last two axes (through the FFT; numpy only), the edges mirrored
    first so the blur does not wrap one edge of a strip onto the other."""
    m = int(np.ceil(3 * sigma))
    b = np.pad(a, ((0, 0), (m, m), (m, m)), mode="reflect") if m else a
    h, w = b.shape[-2:]
    fy, fx = np.fft.fftfreq(h)[:, None], np.fft.rfftfreq(w)[None, :]
    k = np.exp(-2 * (np.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))
    out = np.fft.irfft2(np.fft.rfft2(b) * k, s=(h, w)).astype(np.float32)
    return out[:, m:h - m, m:w - m] if m else out


def _prepare(a: np.ndarray, px: float) -> np.ndarray:
    """What two tiles are matched on: log intensity, band-passed per slice (fine structure kept,
    the slow background and the shot noise dropped), each slice to zero mean and unit spread —
    so a dimmer tile or a darker slice matches as well as a bright one."""
    a = np.log1p(np.maximum(a - np.percentile(a, 1), 0)).astype(np.float32)
    a = _smooth(a, 0.7 / px) - _smooth(a, 4.0 / px)
    a -= a.mean(axis=(1, 2), keepdims=True)
    a /= a.std(axis=(1, 2), keepdims=True) + 1e-6
    return a


def _corr(x: np.ndarray, y: np.ndarray, shape) -> np.ndarray:
    ax = tuple(range(len(shape)))
    return np.fft.irfftn(np.fft.rfftn(x, shape, ax) * np.conj(np.fft.rfftn(y, shape, ax)), shape, ax)


def _match(A: np.ndarray, B: np.ndarray, max_shift, min_frac: float = 0.4):
    """The shift d (z, y, x) for which A(p + d) best matches B(p): masked normalised cross-
    correlation over every shift within ``max_shift``, counting only where both volumes are
    (Padfield 2012), so a shift that leaves a thin sliver of overlap cannot win on a few voxels.
    Returns (d with sub-voxel x and y, the peak correlation)."""
    shape = tuple(int(n + m + 1) for n, m in zip(A.shape, max_shift))
    MA, MB = np.ones_like(A), np.ones_like(B)
    n = _corr(MA, MB, shape)
    sA, sB = _corr(A, MB, shape), _corr(MA, B, shape)
    sAA, sBB, sAB = _corr(A * A, MB, shape), _corr(MA, B * B, shape), _corr(A, B, shape)
    with np.errstate(invalid="ignore", divide="ignore"):
        num = sAB - sA * sB / n
        den = np.sqrt(np.maximum(sAA - sA * sA / n, 0) * np.maximum(sBB - sB * sB / n, 0))
        ncc = np.where((n >= min_frac * A.size) & (den > 0), num / den, -1.0)
    # shifts within the limits only (index d, or shape + d for a negative d)
    keep = np.zeros(shape, bool)
    rngs = [np.r_[0:m + 1, s - m:s] for m, s in zip(max_shift, shape)]
    keep[np.ix_(*rngs)] = True
    ncc = np.where(keep, ncc, -1.0)
    i = np.unravel_index(int(np.argmax(ncc)), shape)
    d = [float(k if k <= m else k - s) for k, m, s in zip(i, max_shift, shape)]
    for ax in (1, 2):                                   # parabola through the peak along x and y
        lo, hi = list(i), list(i)
        lo[ax] = (i[ax] - 1) % shape[ax]
        hi[ax] = (i[ax] + 1) % shape[ax]
        a_, b_, c_ = ncc[tuple(lo)], ncc[i], ncc[tuple(hi)]
        den_ = a_ - 2 * b_ + c_
        if a_ > -1 and c_ > -1 and den_ < 0:
            d[ax] += float(np.clip(0.5 * (a_ - c_) / den_, -0.5, 0.5))
    return d, float(ncc[i])


def register(mesc, ts: List[Tile], layout=None, channel: int = 0, max_shift_um: float = 15.0,
             max_dz_um: float = 15.0, down: int = 2, min_overlap_um: float = 8.0,
             min_score: float = 0.15, fixed: Optional[str] = None) -> dict:
    """Correct the tiles from their overlaps, starting from ``layout`` (so a hand-made layout is
    refined, not thrown away). Each pair overlapping by at least ``min_overlap_um`` is matched in
    3-D within ±``max_shift_um`` across and ±``max_dz_um`` in depth (on images reduced ``down``
    times across, then the peak refined to a fraction of a pixel); the pairs that match (peak
    correlation ≥ ``min_score``) give one correction per tile by least squares, weighted by the
    correlation, with ``fixed`` (default: the first shown tile) held where it is.

    Returns ``{"layout": the new layout, "pairs": [...], "fixed": path, "unmatched": [...]}``; each
    pair has its correlation, the shift it measured and what is left of it after the solve (its
    residual, µm and slices) — a residual of more than a pixel or a slice is a seam to look at.
    """
    g = geometry(ts, layout)
    place, px, py, dzu = g["place"], g["px"], g["py"], g["dz"]
    paths = [p for p in g["order"]]
    fixed = fixed if fixed in place else paths[0]
    cache: Dict[str, np.ndarray] = {}            # the last few tiles read, stored integers

    def vol(path):
        if path not in cache:
            if len(cache) >= 4:
                cache.pop(next(iter(cache)))
            cache[path] = np.asarray(mesc.read(path, channel=channel, reader_units=False))
        return cache[path]

    ms = (int(round(max_dz_um / dzu)), int(round(max_shift_um / (py * down))), int(round(max_shift_um / (px * down))))
    pairs = []
    for a, b in itertools.combinations(paths, 2):
        A, B = place[a], place[b]
        x0, x1 = max(A["c0"], B["c0"]), min(A["c0"] + A["tile"].width, B["c0"] + B["tile"].width)
        y0, y1 = max(A["r0"], B["r0"]), min(A["r0"] + A["tile"].height, B["r0"] + B["tile"].height)
        if (x1 - x0) * px < min_overlap_um or (y1 - y0) * py < min_overlap_um:
            continue
        # the shared rectangle, in each tile's own reduced pixels; the slices by each tile's dz
        za0, za1 = max(A["z0"], B["z0"]), min(A["z0"] + A["tile"].depth, B["z0"] + B["tile"].depth)
        if za1 - za0 < 4:
            continue
        # cut at full resolution from the same mosaic pixel in both, then reduced: the two grids
        # coincide, so reducing adds no shift of its own
        h, w = (y1 - y0) // down, (x1 - x0) // down

        def cut(P, V):
            v = V[za0 - P["z0"]:za1 - P["z0"], y0 - P["r0"]:y0 - P["r0"] + h * down,
                  x0 - P["c0"]:x0 - P["c0"] + w * down].astype(np.float32)
            return _prepare(v.reshape(v.shape[0], h, down, w, down).mean(axis=(2, 4)), px * down)
        VA, VB = cut(A, vol(a)), cut(B, vol(b))
        lim = (min(ms[0], VA.shape[0] // 2), min(ms[1], h // 2), min(ms[2], w // 2))
        d, r = _match(VA, VB, lim)
        # B's content at p is A's at p + d: B sits d further on than its layout says (µm, slices)
        pairs.append({"a": a, "b": b, "score": r,
                      "shift": [d[2] * px * down, d[1] * py * down, d[0]]})
    good = [p for p in pairs if p["score"] >= min_score]
    idx = {p: i for i, p in enumerate(paths)}
    rows, rhs, w = [], [], []
    for p in good:
        row = np.zeros(len(paths)); row[idx[p["b"]]] = 1; row[idx[p["a"]]] = -1
        rows.append(row); rhs.append(p["shift"]); w.append(p["score"])
    row = np.zeros(len(paths)); row[idx[fixed]] = 1
    rows.append(row); rhs.append([0.0, 0.0, 0.0]); w.append(10.0)
    Aw, bw = np.array(rows) * np.array(w)[:, None], np.array(rhs) * np.array(w)[:, None]
    sol, *_ = np.linalg.lstsq(Aw, bw, rcond=None)
    # a tile no matched pair reaches is left where it was (the solve would put it at 0 anyway)
    linked = {fixed} | {p["a"] for p in good} | {p["b"] for p in good}
    new = {"tiles": {k: dict(v) for k, v in ((layout or {}).get("tiles") or {}).items()},
           "order": list((layout or {}).get("order") or paths), "seams": g["seams"]}
    for path in paths:
        e = _entry(layout, path)
        if path in linked:
            e["dx"] = round(e["dx"] + float(sol[idx[path]][0]), 3)
            e["dy"] = round(e["dy"] + float(sol[idx[path]][1]), 3)
            e["dz"] = int(e["dz"] + _round(float(sol[idx[path]][2])))
        new["tiles"][path] = {**new["tiles"].get(path, {}), **e}
    for p in pairs:
        fit = sol[idx[p["b"]]] - sol[idx[p["a"]]]
        p["residual"] = [round(float(m - f), 3) for m, f in zip(p["shift"], fit)]
        p["used"] = p["score"] >= min_score
        p["shift"] = [round(float(v), 3) for v in p["shift"]]
        p["score"] = round(p["score"], 3)
    return {"layout": new, "pairs": pairs, "fixed": fixed,
            "unmatched": [p for p in paths if p not in linked]}


def to_tiff(mesc, ts: List[Tile], layout, out_path, channels=None, planes=None, crop=None) -> Path:
    """A cut of the mosaic as a Fiji hyperstack (ZCYX, or ZYX for one channel), float32 reader
    units, 0 where no tile reaches; the slice spacing and pixel sizes set, and the layout (each
    tile's correction) written into the Info. Needs tifffile."""
    try:
        import tifffile
    except ImportError as exc:  # noqa: BLE001
        raise ImportError("writing TIFF needs tifffile — pip install mesc-io[tiff]") from exc
    from .export import _DEFAULT_COLOURS, _lut
    g = geometry(ts, layout)
    first = mesc.unit(g["order"][0])
    chans = list(range(len(first.channels))) if channels is None else [int(c) for c in channels]
    vols = [np.nan_to_num(compose(mesc, ts, layout, c, planes, crop)) for c in chans]
    data = np.stack(vols, axis=1) if len(chans) > 1 else vols[0]
    z0, _ = g["planes"]
    info = [f"source_file = {mesc.path.name}", "mosaic of z-stack tiles, hard seams ("
            + g["seams"] + ")", f"first plane = {planes[0] if planes else z0}",
            f"crop (mosaic px) = {list(crop) if crop is not None else 'none'}"]
    for path in g["order"]:
        e = _entry(layout, path)
        info.append(f"{path}: dx = {e['dx']} um, dy = {e['dy']} um, dz = {e['dz']} slices")
    meta = {"axes": "ZCYX" if len(chans) > 1 else "ZYX", "spacing": g["dz"], "unit": "um",
            "Info": "\n".join(info)}
    if len(chans) > 1:
        meta["mode"] = "composite"
        ranges = []
        for v in vols:
            lo, hi = np.percentile(v[v > 0], [1, 99.8]) if (v > 0).any() else (0.0, 1.0)
            ranges += [float(lo), float(hi if hi > lo else lo + 1)]
        meta["Ranges"] = tuple(ranges)
        meta["LUTs"] = [_lut((first.channels[c].colour if first.channels[c].colour and first.channels[c].colour.lower() != "#000000"
                              else _DEFAULT_COLOURS[k % len(_DEFAULT_COLOURS)])) for k, c in enumerate(chans)]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(str(out_path), data.astype(np.float32), imagej=True, metadata=meta,
                     resolution=(1.0 / g["px"], 1.0 / g["py"]))
    return out_path
