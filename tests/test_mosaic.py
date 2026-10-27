"""Mosaics of z-stack tiles: placed by the stage, corrected from the overlaps, composed, cut out.

The synthetic mosaic (tools/make_synthetic.py --mosaic) is six tiles cut from one volume where the
stage did NOT quite go: each tile is off by a known few pixels and slices (MOSAIC_ERRORS). Stitching
must find those errors, and a mosaic put together with them must show the same tissue on both sides
of every seam.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from mesc_io import MescFile
from mesc_io import mosaic as M

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from make_synthetic import MOSAIC_ERRORS, MOSAIC_PX  # noqa: E402


@pytest.fixture(scope="module")
def mos(tmp_path_factory):
    out = tmp_path_factory.mktemp("mosaic") / "mosaic.mesc"
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_synthetic.py"), "--mosaic", str(out)],
                   check=True, capture_output=True)
    return out


def truth(ts):
    return {"tiles": {t.path: {"dx": e[0] * MOSAIC_PX, "dy": e[1] * MOSAIC_PX, "dz": e[2]}
                      for t, e in zip(ts, MOSAIC_ERRORS)}}


def test_the_tiles_are_the_stacks_with_a_stage_position(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
    assert [t.name for t in ts] == [f"MUnit_{i}" for i in range(6)]
    assert ts[1].x_um - ts[0].x_um == pytest.approx(36.0) and ts[3].y_um - ts[0].y_um == pytest.approx(36.0)
    assert (ts[0].depth, ts[0].height, ts[0].width, ts[0].px, ts[0].dz) == (40, 96, 96, 0.5, 1.0)


def test_geometry_places_by_the_stage_and_moves_by_the_layout(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
    g = M.geometry(ts)
    assert (g["place"][ts[1].path]["c0"], g["place"][ts[3].path]["r0"]) == (72, 72)
    assert (g["width"], g["height"], g["planes"]) == (240, 168, (0, 40))
    g = M.geometry(ts, {"tiles": {ts[1].path: {"dx": 1.5, "dy": -1.0, "dz": 2}, ts[5].path: {"hidden": True}}})
    p = g["place"][ts[1].path]
    # 1 µm up moves the origin, so tile 1 is the top row (0) and the others come down by 2 px
    assert (p["c0"], p["r0"], p["z0"]) == (75, 0, 2) and g["place"][ts[0].path]["r0"] == 2
    assert ts[5].path not in g["place"] and g["planes"] == (0, 42)


def test_stitching_finds_where_each_tile_really_is(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
        r = M.register(f, ts)
    assert r["fixed"] == ts[0].path and not r["unmatched"]
    for t, (ex, ey, ez) in zip(ts, MOSAIC_ERRORS):
        e = r["layout"]["tiles"][t.path]
        assert e["dz"] == ez, t.name
        assert abs(e["dx"] - ex * MOSAIC_PX) < 0.5 and abs(e["dy"] - ey * MOSAIC_PX) < 0.5, (t.name, e)
    used = [p for p in r["pairs"] if p["used"]]
    assert len(used) >= 7                                     # the 7 edge pairs at least
    assert max(abs(v) for p in used for v in p["residual"][:2]) < 1.0
    assert all(p["residual"][2] == 0 for p in used)


def test_stitching_refines_a_layout_instead_of_throwing_it_away(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
        start = truth(ts)
        start["tiles"][ts[2].path]["hidden"] = True
        start["seams"] = "order"
        r = M.register(f, ts, start)
    new = r["layout"]
    assert new["tiles"][ts[2].path]["hidden"] is True and new["seams"] == "order"
    assert ts[2].path not in [p["a"] for p in r["pairs"]] + [p["b"] for p in r["pairs"]]
    for t in ts:
        if t.path == ts[2].path:
            continue
        a, b = new["tiles"][t.path], start["tiles"][t.path]
        assert a["dz"] == b["dz"] and abs(a["dx"] - b["dx"]) < 0.5 and abs(a["dy"] - b["dy"]) < 0.5


def seam_agreement(f, ts, layout, plane=25):
    """How alike two neighbours are where they overlap, at one mosaic plane (Pearson r)."""
    g = M.geometry(ts, layout)
    a = M.compose(f, ts, {**layout, "order": [ts[1].path, ts[0].path], "seams": "order"}, planes=[plane])[0]
    b = M.compose(f, ts, {**layout, "order": [ts[0].path, ts[1].path], "seams": "order"}, planes=[plane])[0]
    p0, p1 = g["place"][ts[0].path], g["place"][ts[1].path]
    x0, x1 = p1["c0"], p0["c0"] + 96
    y0, y1 = max(p0["r0"], p1["r0"]), min(p0["r0"], p1["r0"]) + 96
    return np.corrcoef(a[y0:y1, x0:x1].ravel(), b[y0:y1, x0:x1].ravel())[0, 1]


def test_with_the_right_layout_the_seams_show_the_same_tissue(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
        right, raw = seam_agreement(f, ts, truth(ts)), seam_agreement(f, ts, {})
    assert right > 0.8 and raw < 0.5, (right, raw)


def test_nearest_seams_take_each_pixel_from_the_nearest_centre(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
        g = M.geometry(ts)
        m = M.compose(f, ts, {}, planes=[20])[0]
        t0 = f.read(ts[0].path, frames=[20])[0]
        t1 = f.read(ts[1].path, frames=[20])[0]
    # the overlap of tiles 0 and 1 runs over columns 72..95; its left half is nearer tile 0's centre
    assert np.allclose(m[10, 72:84], t0[10, 72:84]) and np.allclose(m[10, 84:96], t1[10, 12:24])
    assert m.shape == (g["height"], g["width"]) and np.isfinite(m).all()


def test_compose_cuts_planes_and_a_crop_and_leaves_empty_places_empty(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
        lay = truth(ts)
        m = M.compose(f, ts, lay, planes=[-2, 0, 41], crop=(10, 20, 50, 60))
        full = M.compose(f, ts, lay, planes=[0])[0]
    assert m.shape == (3, 40, 40)
    assert np.isnan(m[0]).all()               # plane −2 is only tile 6's (dz −2), which is not in this crop
    assert np.allclose(m[1], full[20:60, 10:50], equal_nan=True)


def test_the_tiff_is_a_calibrated_hyperstack_with_the_layout_inside(mos, tmp_path):
    tifffile = pytest.importorskip("tifffile")
    with MescFile(mos) as f:
        ts = M.tiles(f)
        lay = truth(ts)
        out = M.to_tiff(f, ts, lay, tmp_path / "m.tif", planes=list(range(5, 15)), crop=(0, 0, 100, 80))
    with tifffile.TiffFile(out) as tf:
        a, ij = tf.asarray(), tf.imagej_metadata
        xres = tf.pages[0].tags["XResolution"].value
    assert a.shape == (10, 2, 80, 100) and a.dtype == np.float32
    assert ij["spacing"] == pytest.approx(1.0) and ij["unit"] == "um" and ij["mode"] == "composite"
    assert xres[0] / xres[1] == pytest.approx(1 / MOSAIC_PX)
    assert f"{ts[1].path}: dx = 1.5 um, dy = -1.0 um, dz = 2 slices" in ij["Info"]


def test_the_viewer_stitches_and_exports(mos, tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import Request, urlopen
    from mesc_io import viewer
    pytest.importorskip("tifffile")

    class H(viewer._Handler):
        pass
    H.mesc_path, H.rois_path = mos, tmp_path / "m_rois.json"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    post = lambda path, body: json.loads(urlopen(Request(base + path, json.dumps(body).encode(),  # noqa: E731
                                                         {"Content-Type": "application/json"}, method="POST")).read())
    try:
        r = post("/api/mosaic/register", {"layout": {}, "channel": 0})
        assert r["layout"]["tiles"]["MSession_0/MUnit_3"]["dz"] == 3
        e = post("/api/mosaic/export", {"layout": r["layout"], "channels": [0], "planes": [10, 12], "crop": [0, 0, 64, 32]})
        assert Path(e["path"]).parent == tmp_path and e["bytes"] > 64 * 32 * 3 * 4
    finally:
        srv.shutdown()


# -- the harder cases: a wrong match, a tile with nothing in it, a group joined to nothing ----------

def grid_links(errs, cols=3, skip=(), diagonals=False):
    """Exact links between grid neighbours (right and down; with ``diagonals`` the two diagonals
    too, as overlapping corners give) for tiles off by ``errs``."""
    out = []
    for t in range(len(errs)):
        c = t % cols
        nb = [t + 1 if c + 1 < cols else None, t + cols if t + cols < len(errs) else None]
        if diagonals:
            nb += [t + cols + 1 if c + 1 < cols and t + cols + 1 < len(errs) else None,
                   t + cols - 1 if c > 0 and t + cols - 1 < len(errs) else None]
        for u in nb:
            if u is None or (t, u) in skip:
                continue
            out.append({"a": str(t), "b": str(u), "weight": 0.5,
                        "shift": [errs[u][k] - errs[t][k] for k in range(3)]})
    return out


def test_one_wrong_match_is_dropped_not_spread_over_every_tile():
    errs = [np.array(e, float) * [0.5, 0.5, 1] for e in MOSAIC_ERRORS]
    links = grid_links(errs)
    bad = next(ln for ln in links if (ln["a"], ln["b"]) == ("1", "4"))
    bad["shift"] = [bad["shift"][0] + 8.0, bad["shift"][1] - 6.0, bad["shift"][2] + 3]   # a confident wrong peak
    bad["weight"] = 0.9
    sol, dropped, doubt = M._solve([str(i) for i in range(6)], links, "0")
    assert [(d["a"], d["b"]) for d in dropped] == [("1", "4")] and doubt == []
    for i in range(6):
        assert np.allclose(sol[str(i)], errs[i] - errs[0], atol=1e-6), i
    # the same wrong link with plain least squares (no second round) bends the tiles it reaches
    sol1, _, _ = M._solve([str(i) for i in range(6)], links, "0", tol_um=1e9)
    assert np.abs(sol1["4"] - (errs[4] - errs[0])).max() > 1.0


def test_a_group_joined_to_nothing_stays_where_it_was():
    errs = [np.array(e, float) * [0.5, 0.5, 1] for e in MOSAIC_ERRORS]
    # only 2–5 join tiles 2 and 5, and nothing joins them to the rest
    links = [ln for ln in grid_links(errs) if {ln["a"], ln["b"]} <= {"0", "1", "3", "4"} or (ln["a"], ln["b"]) == ("2", "5")]
    sol, dropped, doubt = M._solve([str(i) for i in range(6)], links, "0")
    assert not dropped and not doubt
    assert np.allclose(sol["2"] + sol["5"], 0, atol=1e-9)                    # held: mean correction 0
    assert np.allclose(sol["5"] - sol["2"], errs[5] - errs[2], atol=1e-9)   # but true to each other
    assert np.allclose(sol["4"], errs[4] - errs[0], atol=1e-9)


@pytest.fixture(scope="module")
def mos_blank(mos, tmp_path_factory):
    """The synthetic mosaic with tile 6 (MUnit_5) replaced by noise: nothing in it to match."""
    import shutil
    import h5py
    out = tmp_path_factory.mktemp("blank") / "blank.mesc"
    shutil.copy(mos, out)
    rng = np.random.default_rng(3)
    with h5py.File(out, "r+") as f:
        for k in (0, 1):
            ds = f["MSession_0/MUnit_5"][f"Channel_{k}"]
            ds[...] = rng.normal(ds[...].mean(), 25, ds.shape).clip(0, 65535).astype(ds.dtype)
    return out


def test_a_tile_with_nothing_in_it_is_not_moved_by_chance(mos_blank):
    with MescFile(mos_blank) as f:
        ts = M.tiles(f)
        start = {"tiles": {ts[5].path: {"dx": 0.7, "dy": -0.4, "dz": 1}}}
        r = M.register(f, ts, start)
    p5 = [p for p in r["pairs"] if ts[5].path in (p["a"], p["b"])]
    assert p5 and all(p["status"] in ("weak", "edge") for p in p5), p5
    assert r["unmatched"] == [ts[5].path]
    e = r["layout"]["tiles"][ts[5].path]
    assert (e["dx"], e["dy"], e["dz"]) == (0.7, -0.4, 1)                     # where it started
    for t, (ex, ey, ez) in list(zip(ts, MOSAIC_ERRORS))[:5]:                 # the rest as before
        e = r["layout"]["tiles"][t.path]
        assert e["dz"] == ez and abs(e["dx"] - ex * MOSAIC_PX) < 0.5 and abs(e["dy"] - ey * MOSAIC_PX) < 0.5


def test_the_bar_comes_from_tiles_that_do_not_overlap(mos):
    with MescFile(mos) as f:
        r = M.register(f, M.tiles(f))
    assert len(r["null"]) >= 3 and r["threshold"] == max(0.15, max(r["null"]))
    used = [p for p in r["pairs"] if p["status"] == "used"]
    assert min(p["score"] for p in used) > r["threshold"] and all(p["loop"] for p in used)


@pytest.mark.parametrize("seed", range(20))
def test_matching_noise_singles_nothing_out(seed):
    # every link off by up to ±0.6 µm (the synthetic's own residuals are 0.1–0.6): nothing dropped
    rng = np.random.default_rng(seed)
    errs = [np.array(e, float) * [0.5, 0.5, 1] for e in MOSAIC_ERRORS]
    links = grid_links(errs)
    for ln in links:
        ln["shift"] = [ln["shift"][0] + rng.uniform(-.6, .6), ln["shift"][1] + rng.uniform(-.6, .6), ln["shift"][2]]
    _, dropped, doubt = M._solve([str(i) for i in range(6)], links, "0")
    assert dropped == [] and doubt == []


@pytest.mark.parametrize("seed", range(20))
def test_one_wrong_match_is_found_under_matching_noise(seed):
    rng = np.random.default_rng(100 + seed)
    errs = [np.array(e, float) * [0.5, 0.5, 1] for e in MOSAIC_ERRORS]
    links = grid_links(errs, diagonals=True)                  # as the overlapping corners give
    for ln in links:
        ln["shift"] = [ln["shift"][0] + rng.uniform(-.6, .6), ln["shift"][1] + rng.uniform(-.6, .6), ln["shift"][2]]
    k = int(rng.integers(len(links)))
    links[k]["shift"] = [links[k]["shift"][0] + rng.choice([-1, 1]) * rng.uniform(5, 10), links[k]["shift"][1], links[k]["shift"][2]]
    sol, dropped, doubt = M._solve([str(i) for i in range(6)], links, "0")
    assert [(d["a"], d["b"]) for d in dropped] == [(links[k]["a"], links[k]["b"])] and doubt == []
    for i in range(6):
        assert np.abs(sol[str(i)] - (errs[i] - errs[0]))[:2].max() < 1.0


def test_a_wrong_link_the_loops_cannot_name_is_left_in_doubt_not_guessed():
    # edge neighbours only: link 0–1 is in one four-tile loop with 0–3, 3–4 and 1–4… and 1–4 is in
    # two; a wrong 0–3 cannot be told from a wrong 0–1 or 3–4
    errs = [np.array(e, float) * [0.5, 0.5, 1] for e in MOSAIC_ERRORS]
    links = grid_links(errs)
    bad = next(ln for ln in links if (ln["a"], ln["b"]) == ("0", "3"))
    bad["shift"] = [bad["shift"][0] + 7.0, bad["shift"][1], bad["shift"][2]]
    _, dropped, doubt = M._solve([str(i) for i in range(6)], links, "0")
    assert dropped == [] and {(d["a"], d["b"]) for d in doubt} >= {("0", "3"), ("0", "1"), ("3", "4")}


def test_a_tile_further_off_than_the_overlap_allows_does_not_drag_the_others(tmp_path):
    # tile 5 (MUnit_4) 6 µm off each way: past the small diagonal overlaps' search, which then
    # offer chance peaks on their edges (the case that bent four tiles' depth before)
    import make_synthetic as S
    keep = list(S.MOSAIC_ERRORS)
    try:
        S.MOSAIC_ERRORS[4] = (-12, -12, 1)
        out = tmp_path / "far.mesc"
        S.mosaic(out)
        errs = list(S.MOSAIC_ERRORS)
    finally:
        S.MOSAIC_ERRORS[:] = keep
    with MescFile(out) as f:
        ts = M.tiles(f)
        r = M.register(f, ts)
    for t, (ex, ey, ez) in zip(ts, errs):
        e = r["layout"]["tiles"][t.path]
        assert e["dz"] == ez and abs(e["dx"] - ex * MOSAIC_PX) < 0.5 and abs(e["dy"] - ey * MOSAIC_PX) < 0.5, (t.name, e)
    assert all(p["status"] in ("weak", "edge") for p in r["pairs"] if p["residual"][2] != 0 or abs(p["residual"][0]) > 1)


def test_refining_moves_a_tile_back_from_where_it_was_left(mos):
    # a no-op register would pass the other refine test; this one starts a tile 2 px off
    with MescFile(mos) as f:
        ts = M.tiles(f)
        start = truth(ts)
        start["tiles"][ts[4].path]["dx"] += 1.0
        r = M.register(f, ts, start)
    assert abs(r["layout"]["tiles"][ts[4].path]["dx"] - MOSAIC_ERRORS[4][0] * MOSAIC_PX) < 0.4


def test_the_tiff_is_written_a_plane_at_a_time_not_held_whole(mos, tmp_path):
    pytest.importorskip("tifffile")
    import tracemalloc
    with MescFile(mos) as f:
        ts = M.tiles(f)
        lay = truth(ts)
        whole = M.tiff_bytes(ts, lay, 2)
        tracemalloc.start()
        M.to_tiff(f, ts, lay, tmp_path / "w.tif")
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    assert whole > 10e6 and peak < 0.4 * whole, (peak, whole)
    import tifffile
    a = tifffile.imread(tmp_path / "w.tif")
    assert np.isnan(a).any() and np.isfinite(a).mean() > 0.8      # NaN where no tile, not 0
