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

``dx``, ``dy`` (µm) move a tile from its stage position; ``dz`` (slices) moves it in depth from
where its own geometry puts it. A stack's depth is read from the geometry it carries (``Unit.z0_um``:
slice ``s`` at ``z0_um + s * step``, slice 0 the deep end), never from the stage position, which is
one reading taken at some moment of the scan — 190 µm off on one tile of a 2026-10-27 mosaic whose
geometry was right. Mosaic plane ``q`` is at depth ``z0_um + q * step`` of the deepest tile, so a
tile's slice ``s`` is plane ``s + (its z0 − the deepest z0) / step + dz``; a file without the
geometry puts every slice 0 on plane ``dz``, as before. Tiles commented "ignore" start hidden. Every mosaic pixel comes from ONE tile (hard seams, no blending, so nothing is
averaged that was never one place): with ``"nearest"`` the tile whose centre is nearest, with
``"order"`` the last in ``order`` that covers it. Only numpy is needed; a TIFF needs tifffile.
"""
from __future__ import annotations

import itertools
import re
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
    z0_um: Optional[float] = None       # the depth of slice 0, from the stack's own geometry (rig z, µm)
    z_origin_um: Optional[float] = None  # the rig's zero in z when the stack was taken


def tiles(mesc, paths=None) -> List[Tile]:
    """The file's z-stacks that carry a stage position, in file order (or the ``paths`` given)."""
    units = [u for u in mesc.units() if (paths is None or u.path in paths) and u.z_step_um and u.n_frames >= 2
             and u.pixel_size_um and (u.stage_rel_um or u.stage_um)]
    # one frame of reference for every tile: the position from the rig's zero only when every tile
    # has one (the zero can be set again between tiles, and a tile without it would land in the
    # other frame, silently), else the absolute stage
    rel = all(u.stage_rel_um and "x" in u.stage_rel_um and "y" in u.stage_rel_um for u in units)
    out = []
    for u in units:
        pos = u.stage_rel_um if rel else u.stage_um
        if not pos or "x" not in pos or "y" not in pos:
            continue
        out.append(Tile(u.path, u.name, u.comment or "", u.n_frames, u.height, u.width,
                        float(u.pixel_size_um), float(u.pixel_size_y_um or u.pixel_size_um),
                        float(u.z_step_um), float(pos["x"]), float(pos["y"]), u.z0_um, u.z_origin_um))
    if paths is not None:
        out.sort(key=lambda t: list(paths).index(t.path))
    return out


def _round(v: float) -> int:
    """Half up, as the viewer's Math.round: Python's round() goes to the even neighbour at .5,
    and one pixel of difference would put a tile in another place on screen than in an export."""
    return int(np.floor(v + 0.5))


_IGNORE = re.compile(r"\bignore\b", re.I)


def _entry(layout, path, tile: Optional[Tile] = None) -> dict:
    """A tile's entry in the layout; a tile commented "ignore" (the rig's word for a take to
    throw away) starts hidden until the layout says otherwise."""
    e = ((layout or {}).get("tiles") or {}).get(path) or {}
    hid = e["hidden"] if "hidden" in e else bool(tile is not None and _IGNORE.search(tile.comment or ""))
    return {"dx": float(e.get("dx", 0.0)), "dy": float(e.get("dy", 0.0)),
            "dz": _round(float(e.get("dz", 0))), "hidden": bool(hid)}


def _grid(t: Tile):
    return (round(t.px, 6), round(t.py, 6), round(t.dz, 6))


def geometry(ts: List[Tile], layout=None) -> dict:
    """Where every shown tile sits in the mosaic, in whole mosaic pixels and planes. The grid is
    the one most shown tiles share (pixel size and slice step; ties to the earlier tile); tiles on
    another grid are left out, with the reason — the first tile no longer decides, since the
    injection-zero stack taken first at 10 µm steps silently dropped every real tile behind it.
    The viewer draws by the same rule — top-left = round((centre + correction − half the tile −
    origin) / pixel), plane of slice 0 = round((z0 − deepest z0) / step) + dz — so the screen and
    an export put every voxel in the same place."""
    shown = [t for t in ts if not _entry(layout, t.path, t)["hidden"]]
    if not shown:
        raise ValueError("no tile to show")
    grids = [_grid(t) for t in shown]
    best = max(grids, key=lambda k: (grids.count(k), -grids.index(k)))
    ref = shown[grids.index(best)]
    skipped = {t.path: f"another grid ({t.px:g} µm pixels, {t.dz:g} µm slices) than most tiles' "
                       f"({ref.px:g} µm, {ref.dz:g} µm)" for t in shown if _grid(t) != best}
    shown = [t for t in shown if t.path not in skipped]
    # depth from the stacks' own geometry, when every shown tile carries it
    zbase = min(t.z0_um for t in shown) if all(t.z0_um is not None for t in shown) else None
    lift = {t.path: (_round((t.z0_um - zbase) / ref.dz) if zbase is not None else 0) for t in shown}
    origins = {t.z_origin_um for t in shown}
    left = {t.path: t.x_um + _entry(layout, t.path)["dx"] - t.width * t.px / 2 for t in shown}
    top = {t.path: t.y_um + _entry(layout, t.path)["dy"] - t.height * t.py / 2 for t in shown}
    ox, oy = min(left.values()), min(top.values())
    place = {}
    for t in shown:
        e = _entry(layout, t.path)
        c0, r0 = _round((left[t.path] - ox) / ref.px), _round((top[t.path] - oy) / ref.py)
        place[t.path] = {"c0": c0, "r0": r0, "z0": lift[t.path] + e["dz"], "tile": t,
                         "cx": c0 + t.width / 2, "cy": r0 + t.height / 2}
    W = max(p["c0"] + p["tile"].width for p in place.values())
    H = max(p["r0"] + p["tile"].height for p in place.values())
    z0 = min(p["z0"] for p in place.values())
    z1 = max(p["z0"] + p["tile"].depth for p in place.values())
    order = [p for p in ((layout or {}).get("order") or []) if p in place]
    order += [t.path for t in shown if t.path not in order]
    return {"place": place, "width": W, "height": H, "planes": (z0, z1), "px": ref.px, "py": ref.py,
            "dz": ref.dz, "origin_um": (ox, oy), "order": order, "skipped": skipped,
            "seams": (layout or {}).get("seams", "nearest"),
            # plane q is at rig z  z_um + q * dz;  from the rig's zero when every tile shares it
            "z_um": zbase, "z_zero_um": origins.pop() if len(origins) == 1 and None not in origins else None}


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

def _smooth(a: np.ndarray, sy: float, sx: Optional[float] = None) -> np.ndarray:
    """Gaussian blur over the last two axes, ``sy`` and ``sx`` pixels (through the FFT; numpy
    only), the edges mirrored first so the blur does not wrap one edge of a strip onto the other."""
    sx = sy if sx is None else sx
    my, mx = int(np.ceil(3 * sy)), int(np.ceil(3 * sx))
    b = np.pad(a, ((0, 0), (my, my), (mx, mx)), mode="reflect")
    h, w = b.shape[-2:]
    fy, fx = np.fft.fftfreq(h)[:, None], np.fft.rfftfreq(w)[None, :]
    k = np.exp(-2 * np.pi ** 2 * ((sx * fx) ** 2 + (sy * fy) ** 2))
    out = np.fft.irfft2(np.fft.rfft2(b) * k, s=(h, w)).astype(np.float32)
    return out[:, my:h - my, mx:w - mx]


def _prepare(a: np.ndarray, px: float, py: Optional[float] = None) -> np.ndarray:
    """What two tiles are matched on: log intensity, band-passed per slice (fine structure kept,
    the slow background and the shot noise dropped), each slice to zero mean and unit spread —
    so a dimmer tile or a darker slice matches as well as a bright one."""
    a = np.log1p(np.maximum(a - np.percentile(a, 1), 0)).astype(np.float32)
    py = px if py is None else py
    a = _smooth(a, 0.7 / py, 0.7 / px) - _smooth(a, 4.0 / py, 4.0 / px)
    a -= a.mean(axis=(1, 2), keepdims=True)
    a /= a.std(axis=(1, 2), keepdims=True) + 1e-6
    return a


def _corr(x: np.ndarray, y: np.ndarray, shape) -> np.ndarray:
    ax = tuple(range(len(shape)))
    return np.fft.irfftn(np.fft.rfftn(x, shape, ax) * np.conj(np.fft.rfftn(y, shape, ax)), shape, ax)


def _match(A: np.ndarray, B: np.ndarray, max_shift, min_frac: float = 0.4, apart=(1, 2, 2)):
    """The shift d (z, y, x) for which A(p + d) best matches B(p): masked normalised cross-
    correlation over every shift within ``max_shift``, counting only where both volumes are
    (Padfield 2012), so a shift that leaves a thin sliver of overlap cannot win on a few voxels.
    Every shift is scored directly, so there is no wrap-around to resolve and the best is the
    best; but a periodic or empty overlap has several near-equal peaks, so the runner-up — the
    best shift more than 2 voxels (1 slice) from the winner — is returned too.
    Returns (d with sub-voxel x and y, the peak correlation, the runner-up's correlation)."""
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
    away = ncc.copy()
    near = [np.arange(c - r, c + r + 1) % s for c, r, s in zip(i, apart, shape)]
    away[np.ix_(*near)] = -1.0
    second = float(away.max())
    for ax in (1, 2):                                   # parabola through the peak along x and y
        lo, hi = list(i), list(i)
        lo[ax] = (i[ax] - 1) % shape[ax]
        hi[ax] = (i[ax] + 1) % shape[ax]
        a_, b_, c_ = ncc[tuple(lo)], ncc[i], ncc[tuple(hi)]
        den_ = a_ - 2 * b_ + c_
        if a_ > -1 and c_ > -1 and den_ < 0:
            d[ax] += float(np.clip(0.5 * (a_ - c_) / den_, -0.5, 0.5))
    return d, float(ncc[i]), second


def _components(paths, links):
    """The groups of tiles joined by links (union–find)."""
    root = {p: p for p in paths}

    def find(p):
        while root[p] != p:
            root[p] = root[root[p]]
            p = root[p]
        return p
    for ln in links:
        root[find(ln["a"])] = find(ln["b"])
    groups: Dict[str, list] = {}
    for p in paths:
        groups.setdefault(find(p), []).append(p)
    return list(groups.values())


def _lsq(paths, links, fixed):
    idx = {p: i for i, p in enumerate(paths)}
    rows, rhs, w = [], [], []
    for ln in links:
        r = np.zeros(len(paths)); r[idx[ln["b"]]] = 1; r[idx[ln["a"]]] = -1
        rows.append(r); rhs.append(ln["shift"]); w.append(ln["weight"])
    for gr in _components(paths, links):
        # the group with the fixed tile is pinned by it; any other group is held where it
        # started (its mean correction 0) — not thrown wherever a minimum-norm solution puts it
        r = np.zeros(len(paths))
        if fixed in gr:
            r[idx[fixed]] = 1
        else:
            r[[idx[p] for p in gr]] = 1.0 / len(gr)
        rows.append(r); rhs.append([0.0, 0.0, 0.0]); w.append(100.0)
    sw = np.sqrt(np.array(w))[:, None]             # rows by √weight: the squares are then weighted by it
    sol, *_ = np.linalg.lstsq(np.array(rows) * sw, np.array(rhs) * sw, rcond=None)
    return {p: sol[idx[p]] for p in paths}


def _in_loop(paths, links, k):
    """Whether other links also join the two tiles of link ``k`` (so it can be checked at all)."""
    ln, rest = links[k], links[:k] + links[k + 1:]
    return any(ln["a"] in gr and ln["b"] in gr for gr in _components(paths, rest))


def _solve(paths, links, fixed, dz_um: float = 1.0, max_ratio: float = 2.5, tol_um: float = 3.0,
           tol_z_um: float = 6.0):
    """One correction (dx µm, dy µm, dz slices) per tile from pairwise links — each link says
    ``b − a = shift`` with a weight — by weighted least squares, ``fixed`` held at 0.

    A wrong match must not bend every tile it reaches, and least squares hides it: in a grid it
    spreads its error round every loop it is in. So each link is checked against what the OTHER
    links say about its two tiles (leave one out). A link whose disagreement is over ``tol_um``
    (depth counted in µm, at ``tol_um / tol_z_um`` of its weight: a two-photon focus is several
    times longer in z than across, and the brain drifts in z within a stack, so loops of real
    matches close to ~2–4 slices in depth while they close to a micron or two across — measured on
    three 2026-10 mosaics) is a suspect; the suspect whose removal leaves the links still checked
    by a loop agreeing best is dropped, and everything solved again — but only if, without it,
    they agree within ``tol_um`` and ``max_ratio`` times better than without any other suspect.
    Otherwise the loops cannot tell which is wrong —
    in a grid of only edge neighbours, one bad link of a four-tile loop looks exactly like any
    other of the four — so none is dropped and they are all returned as doubtful, for an eye.
    (Diagonal neighbours add loops; with them a single wrong link can usually be named.)
    Tiles left joined to nothing are held where they started.

    Returns (corrections {path: array(3)}, the links dropped, the links in doubt)."""
    to_um = np.array([1.0, 1.0, dz_um * tol_um / tol_z_um])
    err = lambda s, ln: float(np.linalg.norm((np.asarray(ln["shift"]) - (s[ln["b"]] - s[ln["a"]])) * to_um))  # noqa: E731
    live, dropped, doubt = list(links), [], []
    while len(live) >= 3:
        loo = []
        for k, ln in enumerate(live):
            loo.append(err(_lsq(paths, live[:k] + live[k + 1:], fixed), ln) if _in_loop(paths, live, k) else 0.0)
        suspects = [int(k) for k in np.argsort(loo)[::-1] if loo[k] > tol_um]
        if not suspects:
            break
        left = {}                                     # how well the rest agrees without each suspect
        for k in suspects:
            rest = live[:k] + live[k + 1:]
            checked = [ln for j, ln in enumerate(rest) if _in_loop(paths, rest, j)]
            if checked:
                s = _lsq(paths, rest, fixed)
                left[k] = max(err(s, ln) for ln in checked)
        rank = sorted(left, key=left.get)
        if rank and left[rank[0]] <= tol_um and (len(rank) == 1 or left[rank[1]] > max_ratio * max(left[rank[0]], 1e-9)):
            dropped.append(live.pop(rank[0]))
            continue
        doubt = [live[k] for k in suspects]
        break
    return _lsq(paths, live, fixed), dropped, doubt


def _xy(RA: np.ndarray, RB: np.ndarray, lim_yx, px: float, py: float):
    """The x-y shift of two overlap strips (z, y, x; raw, reduced), matched on their maximum
    through depth: a sparse axon is a line there and a few faint dots in any one slice, and an axon
    running down through the slices made a matched 3-D voxel peak a ridge in z, its runner-up as
    high as itself (0.244 against 0.243 on every pair of a 2026-10-27 mosaic). The runner-up is
    the best shift more than 3 reduced pixels away — another place, not the same one blurred.
    Returns ((dy, dx) sub-pixel, peak, runner-up)."""
    A = _prepare(RA.max(axis=0)[None], px, py)
    B = _prepare(RB.max(axis=0)[None], px, py)
    d, r, r2 = _match(A, B, (0, *lim_yx), apart=(0, 3, 3))
    return (d[1], d[2]), r, r2


def _z(RA: np.ndarray, RB: np.ndarray, dy: int, dx: int, lim_z: int, slab: int):
    """With x-y fixed, the slice shift: slabs of ``slab`` slices (their maximum, prepared) of A
    matched against B's at every offset within ±``lim_z``, the mean correlation over the slabs
    both reach — the depth where the two tiles show the same tissue. Returns (dz in whole slices,
    its mean correlation); dz in the convention of ``_match``: A(z + dz) ≈ B(z)."""
    h, w = RA.shape[1:]
    y0, y1, x0, x1 = max(0, dy), min(h, h + dy), max(0, dx), min(w, w + dx)
    if y1 - y0 < 4 or x1 - x0 < 4:
        return 0.0, -1.0
    A = RA[:, y0:y1, x0:x1].astype(np.float32)
    B = RB[:, y0 - dy:y1 - dy, x0 - dx:x1 - dx].astype(np.float32)
    nz = A.shape[0]

    def slabs(V):
        return {s0: _prepare(V[s0:s0 + slab].max(axis=0)[None], 1.0)[0] for s0 in range(0, max(1, nz - slab + 1))}
    SA, SB = slabs(A), slabs(B)
    score = {}
    for dz in range(-lim_z, lim_z + 1):
        c = [float((SA[z + dz] * SB[z]).mean()) for z in SB if z + dz in SA]
        if len(c) >= 2:
            score[dz] = float(np.mean(c))
    if not score:
        return 0.0, -1.0
    # whole slices: a layout keeps depth in slices, and a sub-slice parabola on these broad peaks
    # (a focus several slices long) was biased by up to ~0.5 slice, enough to round a tile one off
    best = max(score, key=score.get)
    return float(best), score[best]


def register(mesc, ts: List[Tile], layout=None, channel: int = 0, max_shift_um: float = 25.0,
             max_dz_um: float = 15.0, down: int = 2, min_overlap_um: float = 8.0,
             min_score: float = 0.1, fixed: Optional[str] = None, null_samples: int = 24,
             distinct: float = 1.5, slab_um: float = 6.0) -> dict:
    """Correct the tiles from their overlaps, starting from ``layout`` (so a hand-made layout is
    refined, not thrown away). Each pair overlapping by at least ``min_overlap_um`` (and sharing
    depth, by the stacks' geometry) is matched in two steps: across, within ±``max_shift_um``, on
    the maximum through their common depth (``_xy``); then in depth, within ±``max_dz_um``, on
    slabs of ``slab_um`` (``_z``) — how far the stage (and the brain, ~10 µm in z between stacks)
    can plausibly be off; no tile is ever moved further from where it started than that (on
    images reduced ``down`` times across, then the peak refined to a fraction of a pixel). A match
    must stand ``distinct`` times above the best one elsewhere, or it is ``ambiguous``.

    Which matches to believe is decided by the data, as ASHLAR does: the same strips are matched
    against tiles that do NOT overlap, and the best of those chance correlations is the bar a real
    pair must clear (never below ``min_score``). Sparse axons in a dark field correlate weakly
    everywhere, so a fixed bar is either too strict for them or too loose for an empty overlap.
    The pairs that clear it give one correction per tile (``_solve``: weighted least squares,
    outlier links dropped, unjoined groups held where they were), ``fixed`` (default: the first
    shown tile) held still.

    Returns ``{"layout", "pairs", "fixed", "unmatched", "threshold", "null"}``. Each pair has its
    correlation, the runner-up peak's, the shift it measured, what is left of it after the solve
    (µm, µm, slices), a ``status`` — ``used``, ``weak`` (below the bar), ``edge`` (its best match
    on the edge of the search: the tile is further off than searched), ``outlier`` (dropped
    for disagreeing with the others) or ``doubt`` (kept, but one of several links a loop says
    cannot all be right: look at these seams) — and ``loop``: whether other links also join its two tiles,
    i.e. whether it was checked at all (a link no loop runs through is believed unchecked).
    """
    g = geometry(ts, layout)
    place, px, py, dzu = g["place"], g["px"], g["py"], abs(g["dz"])
    if not dzu:
        raise ValueError("the tiles have no slice step")
    paths = [p for p in g["order"]]
    fixed = fixed if fixed in place else paths[0]
    cache: Dict[str, np.ndarray] = {}            # the last few tiles read, stored integers

    def vol(path):
        if path not in cache:
            if len(cache) >= 4:
                cache.pop(next(iter(cache)))
            cache[path] = np.asarray(mesc.read(path, channel=channel, reader_units=False))
        return cache[path]

    def lims(dn):
        return (int(round(max_dz_um / dzu)), int(round(max_shift_um / (py * dn))), int(round(max_shift_um / (px * dn))))

    def overlap(A, B):
        x0, x1 = max(A["c0"], B["c0"]), min(A["c0"] + A["tile"].width, B["c0"] + B["tile"].width)
        y0, y1 = max(A["r0"], B["r0"]), min(A["r0"] + A["tile"].height, B["r0"] + B["tile"].height)
        za0, za1 = max(A["z0"], B["z0"]), min(A["z0"] + A["tile"].depth, B["z0"] + B["tile"].depth)
        return x0, x1, y0, y1, za0, za1

    def strip(P, path, x0, y0, h, w, za0, za1, down):
        # cut at full resolution from the same mosaic pixel in both tiles, then reduced: the two
        # grids coincide, so reducing adds no shift of its own
        v = vol(path)[za0 - P["z0"]:za1 - P["z0"], y0 - P["r0"]:y0 - P["r0"] + h * down,
                      x0 - P["c0"]:x0 - P["c0"] + w * down].astype(np.float32)
        return v.reshape(v.shape[0], h, down, w, down).mean(axis=(2, 4))
    slab = max(2, int(round(slab_um / dzu)))

    pairs, geo = [], {}
    for a, b in itertools.combinations(paths, 2):
        A, B = place[a], place[b]
        x0, x1, y0, y1, za0, za1 = overlap(A, B)
        if (x1 - x0) * px < min_overlap_um or (y1 - y0) * py < min_overlap_um or za1 - za0 < 4:
            continue
        # reduced ``down`` times across, unless that leaves the strip narrower than 32 pixels: a
        # few dozen pixels of a narrow overlap match a stranger by chance as well as their partner
        dn = down if min(y1 - y0, x1 - x0) // down >= 32 else 1
        h, w = (y1 - y0) // dn, (x1 - x0) // dn
        VA, VB = strip(A, a, x0, y0, h, w, za0, za1, dn), strip(B, b, x0, y0, h, w, za0, za1, dn)
        ms = lims(dn)
        lim = (min(ms[0], max(0, (VA.shape[0] - 2 * slab) // 2)), min(ms[1], h // 2), min(ms[2], w // 2))
        (dy, dx), r, r2 = _xy(VA, VB, lim[1:], px * dn, py * dn)
        dz, _ = _z(VA, VB, int(round(dy)), int(round(dx)), lim[0], slab) if lim[0] > 0 else (0.0, 0.0)
        d = (dz, dy, dx)
        geo[(a, b)] = (x0, y0, h, w, za0, za1, lim, dn)
        # a peak on the edge of the search is no peak: the true shift is further out, and the best
        # the window could offer is whatever chance put there
        edge = any(m > 0 and abs(round(v)) >= m for v, m in zip(d, lim))
        # B's content at p is A's at p + d: B sits d further on than its layout says (µm, slices)
        pairs.append({"a": a, "b": b, "score": r, "second": r2, "edge": edge,
                      "shift": [d[2] * px * dn, d[1] * py * dn, d[0]]})

    # the bar: the same strips of A matched against tiles that share nothing with A — any
    # correlation found there is chance (the strip is cut from the other tile at the place B's
    # was, relative to its corner, with the depth clipped to that tile)
    null = []
    overl = {(p["a"], p["b"]) for p in pairs} | {(p["b"], p["a"]) for p in pairs}
    for p in pairs:
        if len(null) >= null_samples:
            break
        a, b = p["a"], p["b"]
        x0, y0, h, w, za0, za1, lim, dn = geo[(a, b)]
        B = place[b]
        for c in paths:
            if c in (a, b) or (a, c) in overl or len(null) >= null_samples:
                continue
            C = place[c]
            ox, oy = x0 - B["c0"] + C["c0"], y0 - B["r0"] + C["r0"]   # the same place in C
            z0c, z1c = max(za0, C["z0"]), min(za1, C["z0"] + C["tile"].depth)
            if z1c - z0c < 4 or C["tile"].width < (x0 - B["c0"]) + w * dn or C["tile"].height < (y0 - B["r0"]) + h * dn:
                continue
            VA = strip(place[a], a, x0, y0, h, w, z0c, z1c, dn)
            VC = strip(C, c, ox, oy, h, w, z0c, z1c, dn)
            null.append(_xy(VA, VC, lim[1:], px * dn, py * dn)[1])
            break                                    # one stranger per pair: spread over pairs
    bar = max(min_score, max(null)) if len(null) >= 3 else min_score

    links = [{"a": p["a"], "b": p["b"], "shift": p["shift"], "weight": max(p["score"], 1e-3)}
             for p in pairs if p["score"] >= bar and not p["edge"] and p["score"] >= distinct * max(p["second"], 0)]
    sol, dropped, doubt = _solve(paths, links, fixed, dz_um=dzu)
    out_keys = {(ln["a"], ln["b"]) for ln in dropped}
    doubt_keys = {(ln["a"], ln["b"]) for ln in doubt}
    used = [ln for ln in links if (ln["a"], ln["b"]) not in out_keys]
    groups = _components(paths, used)
    joined = next(gr for gr in groups if fixed in gr)

    new = {"tiles": {k: dict(v) for k, v in ((layout or {}).get("tiles") or {}).items()},
           "order": list((layout or {}).get("order") or paths), "seams": g["seams"]}
    for path in paths:
        e = _entry(layout, path)
        e["dx"] = round(e["dx"] + float(sol[path][0]), 3)
        e["dy"] = round(e["dy"] + float(sol[path][1]), 3)
        e["dz"] = int(e["dz"] + _round(float(sol[path][2])))
        new["tiles"][path] = {**new["tiles"].get(path, {}), **e}
    for p in pairs:
        key = (p["a"], p["b"])
        fit = sol[p["b"]] - sol[p["a"]]
        p["residual"] = [round(float(m - f), 3) for m, f in zip(p["shift"], fit)]
        p["status"] = ("edge" if p["edge"] else "weak" if p["score"] < bar
                       else "ambiguous" if p["score"] < distinct * max(p["second"], 0)
                       else "outlier" if key in out_keys else "doubt" if key in doubt_keys else "used")
        p["used"] = p["status"] in ("used", "doubt")
        others = [ln for ln in used if (ln["a"], ln["b"]) != key]
        p["loop"] = any(p["a"] in gr and p["b"] in gr for gr in _components(paths, others))
        p["shift"] = [round(float(v), 3) for v in p["shift"]]
        p["score"], p["second"] = round(p["score"], 3), round(p["second"], 3)
    return {"layout": new, "pairs": pairs, "fixed": fixed, "threshold": round(bar, 3),
            "null": [round(v, 3) for v in sorted(null)],
            "unmatched": [p for p in paths if p not in joined]}


def tiff_bytes(ts: List[Tile], layout, channels=1, planes=None, crop=None) -> int:
    """What a TIFF of this cut would weigh, float32, before writing it."""
    g = geometry(ts, layout)
    z0, z1 = g["planes"]
    n = (int(planes[1]) - int(planes[0]) + 1) if planes else z1 - z0
    x0, y0, x1, y1 = crop if crop is not None else (0, 0, g["width"], g["height"])
    w, h = min(g["width"], int(x1)) - max(0, int(x0)), min(g["height"], int(y1)) - max(0, int(y0))
    return max(0, n) * max(1, int(channels)) * max(0, w) * max(0, h) * 4


def to_tiff(mesc, ts: List[Tile], layout, out_path, channels=None, planes=None, crop=None) -> Path:
    """A cut of the mosaic as a Fiji hyperstack (ZCYX, or ZYX for one channel), float32 reader
    units, NaN where no tile reaches (0 is a value a recording can hold; NaN is not); the slice
    spacing and pixel sizes set, and the layout (each tile's correction) written into the Info.
    Written a plane at a time, so a whole field of twenty tiles never sits in memory — only one
    plane of it does. ``planes`` is a list of mosaic planes (default all). Needs tifffile."""
    try:
        import tifffile
    except ImportError as exc:  # noqa: BLE001
        raise ImportError("writing TIFF needs tifffile — pip install mesc-io[tiff]") from exc
    from .export import _DEFAULT_COLOURS, _lut
    g = geometry(ts, layout)
    first = mesc.unit(g["order"][0])
    chans = list(range(len(first.channels))) if channels is None else [int(c) for c in channels]
    z0, z1 = g["planes"]
    planes = list(range(z0, z1)) if planes is None else [int(p) for p in planes]
    info = [f"source_file = {mesc.path.name}", "mosaic of z-stack tiles, hard seams ("
            + g["seams"] + "), NaN where no tile reaches", f"first plane = {planes[0]}",
            f"crop (mosaic px) = {list(crop) if crop is not None else 'none'}"]
    for path in g["order"]:
        e = _entry(layout, path)
        info.append(f"{path}: dx = {e['dx']} um, dy = {e['dy']} um, dz = {e['dz']} slices")
    meta = {"axes": "ZCYX" if len(chans) > 1 else "ZYX", "spacing": abs(g["dz"]), "unit": "um",
            "Info": "\n".join(info)}
    probe = compose(mesc, ts, layout, chans[0], planes[:1], crop)[0]
    h, w = probe.shape
    if len(chans) > 1:
        # each channel its own display range, from a few planes spread through the cut
        meta["mode"] = "composite"
        ranges = []
        some = planes[:: max(1, len(planes) // 8)][:8]
        for c in chans:
            v = compose(mesc, ts, layout, c, some, crop)
            v = v[np.isfinite(v)]
            lo, hi = np.percentile(v, [1, 99.8]) if v.size else (0.0, 1.0)
            ranges += [float(lo), float(hi if hi > lo else lo + 1)]
        meta["Ranges"] = tuple(ranges)
        meta["LUTs"] = [_lut((first.channels[c].colour if first.channels[c].colour and first.channels[c].colour.lower() != "#000000"
                              else _DEFAULT_COLOURS[k % len(_DEFAULT_COLOURS)])) for k, c in enumerate(chans)]

    def pages():
        for q in planes:
            for c in chans:
                yield compose(mesc, ts, layout, c, [q], crop)[0]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shape = (len(planes), len(chans), h, w) if len(chans) > 1 else (len(planes), h, w)
    tifffile.imwrite(str(out_path), pages(), shape=shape, dtype=np.float32, imagej=True, metadata=meta,
                     resolution=(1.0 / g["px"], 1.0 / g["py"]))
    return out_path
