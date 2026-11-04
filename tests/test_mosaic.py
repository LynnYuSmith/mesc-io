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


def test_a_link_is_believed_by_its_own_correlation_map(mos):
    # each pair's peak against all the other shifts it tried (peak-to-sidelobe ratio): a strong one
    # is used, a softer one only when the other links confirm it, nothing below the soft level
    with MescFile(mos) as f:
        r = M.register(f, M.tiles(f))
    assert r["threshold"] == 6.0 and "null" not in r
    for p in r["pairs"]:
        if p["status"] in ("used", "doubt"):
            assert p["psr"] >= 4.0 and p["score"] >= 0.1
        if p["status"] == "used" and p["psr"] < 6.0:
            assert p["loop"], p                      # a soft link is used only inside a loop
        if p["psr"] < 4.0:
            assert p["status"] in ("weak", "edge"), p


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
    # no tile is put in a wrong place: within every group of tiles joined by used links, each sits
    # where it really is relative to the others (a group not joined to tile 0 is held where the
    # stage put it) — a far tile neither drags the others nor is guessed
    used = [(p["a"], p["b"]) for p in r["pairs"] if p["used"]]
    groups = M._components([t.path for t in ts], [{"a": a, "b": b} for a, b in used])
    E = {t.path: np.array(e, float) * [MOSAIC_PX, MOSAIC_PX, 1] for t, e in zip(ts, errs)}
    L = {t.path: np.array([r["layout"]["tiles"][t.path][k] for k in ("dx", "dy", "dz")], float) for t in ts}
    for gr in groups:
        gr = sorted(gr)
        for q in gr[1:]:
            d = (L[q] - L[gr[0]]) - (E[q] - E[gr[0]])
            assert abs(d[0]) < 0.5 and abs(d[1]) < 0.5 and d[2] == 0, (gr[0], q, d)
    assert all(p["status"] in ("weak", "edge", "unconfirmed") for p in r["pairs"] if p["residual"][2] != 0 or abs(p["residual"][0]) > 1)


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


# -- what a real two-layer mosaic (October 2026) taught ------------------------------------------------

def _edited(src, dst, edit):
    """A copy of the synthetic mosaic with some unit attributes changed."""
    import shutil
    import h5py
    shutil.copy(src, dst)
    with h5py.File(dst, "r+") as h:
        edit(h["MSession_0"])
    return dst


def _geom_z(units, z0s, origin=-27013.5, step=1.0, offset=-20.0):
    """Give tiles the geometry MESc writes: GeomTransTransl z (the stack's centre) and the z axis's
    conversion offset, so slice 0 sits at centre + offset."""
    for name, z0 in z0s.items():
        a = units[name].attrs
        a["GeomTransTransl"] = np.array([0.0, 0.0, z0 - offset])
        a["ZAxisConversionConversionLinearOffset"] = offset
        a["LabelingOriginTransl"] = np.array([0.0, 0.0, origin])


def test_depth_comes_from_the_stacks_geometry_not_the_stage(mos, tmp_path):
    # tiles 3..5 a second layer, 30 µm shallower; the stage z of the file is left as it is
    lay = {f"MUnit_{i}": -27200.0 for i in range(3)} | {f"MUnit_{i}": -27170.0 for i in range(3, 6)}
    p = _edited(mos, tmp_path / "layers.mesc", lambda u: _geom_z(u, lay))
    with MescFile(p) as f:
        ts = M.tiles(f)
        assert ts[0].z0_um == pytest.approx(-27200.0) and ts[4].z0_um == pytest.approx(-27170.0)
        g = M.geometry(ts)
        compose = M.compose(f, ts, {}, planes=[35])[0]
        t0 = f.read(ts[0].path, frames=[35])[0]
    assert [g["place"][t.path]["z0"] for t in ts] == [0, 0, 0, 30, 30, 30]
    assert g["planes"] == (0, 70) and g["z_um"] == pytest.approx(-27200.0) and g["z_zero_um"] == pytest.approx(-27013.5)
    # plane 35 is slice 35 of the deep row and slice 5 of the shallow one: the deep tile's own pixels
    assert np.allclose(compose[10, 10:40], t0[10, 10:40])
    # the layout's dz is a correction on top of the geometry, not a replacement for it
    g2 = M.geometry(ts, {"tiles": {ts[4].path: {"dz": -2}}})
    assert g2["place"][ts[4].path]["z0"] == 28


def test_a_file_without_the_geometry_keeps_every_slice_0_on_plane_dz(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
    assert all(t.z0_um is None for t in ts)
    g = M.geometry(ts)
    assert {p["z0"] for p in g["place"].values()} == {0} and g["z_um"] is None


def test_a_stack_on_another_grid_first_in_the_file_does_not_drop_the_rest(mos, tmp_path):
    # the injection-zero stack is taken first, at 10 µm slices: it used to be the reference and
    # every real tile was "another pixel size", silently, leaving a mosaic of one tile
    def odd_first(u):
        u["MUnit_0"].attrs["ZAxisConversionConversionLinearScale"] = 10.0
    p = _edited(mos, tmp_path / "injzero.mesc", odd_first)
    with MescFile(p) as f:
        ts = M.tiles(f)
        g = M.geometry(ts)
        r = M.register(f, ts)
    assert list(g["skipped"]) == [ts[0].path] and "10 µm slices" in g["skipped"][ts[0].path]
    assert sorted(g["place"]) == sorted(t.path for t in ts[1:])
    assert ts[0].path not in r["layout"]["tiles"] and r["fixed"] == ts[1].path


def test_a_tile_commented_ignore_starts_hidden_until_the_layout_shows_it(mos, tmp_path):
    def ignore(u):
        u["MUnit_2"].attrs["Comment"] = np.frombuffer(b"ignore\x00", dtype=np.uint8)
    p = _edited(mos, tmp_path / "ignore.mesc", ignore)
    with MescFile(p) as f:
        ts = M.tiles(f)
    assert ts[2].comment == "ignore"
    assert ts[2].path not in M.geometry(ts)["place"] and not M.geometry(ts)["skipped"]
    assert ts[2].path in M.geometry(ts, {"tiles": {ts[2].path: {"hidden": False}}})["place"]
    # "ignored" or a longer word is not the rig's mark
    assert not M._IGNORE.search("not ignored here")


# -- what the red team of 2026-10-28 found ------------------------------------------------------

def test_refining_a_layout_off_by_a_fraction_of_a_pixel_returns_to_the_truth(mos):
    # the shift is measured between tiles as drawn (whole pixels): a start between pixels kept up
    # to half a pixel of error, on the side the rounding went, and auto never settled
    with MescFile(mos) as f:
        ts = M.tiles(f)
        for off in (0.24, 0.26, -0.24, -0.26):
            start = truth(ts)
            start["tiles"][ts[1].path]["dx"] += off
            e = M.register(f, ts, start)["layout"]["tiles"][ts[1].path]
            assert abs(e["dx"] - MOSAIC_ERRORS[1][0] * MOSAIC_PX) < 0.1, (off, e)


def test_auto_settles(mos):
    # from a start off by a fraction of a pixel everywhere: the first auto lands near the truth, the
    # second refines it, and a third changes nothing — before, every auto moved tiles again
    with MescFile(mos) as f:
        ts = M.tiles(f)
        start = {"tiles": {t.path: {"dx": 0.13 * i, "dy": -0.07 * i} for i, t in enumerate(ts)}}
        a = M.register(f, ts, start)["layout"]
        b = M.register(f, ts, a)["layout"]
        c = M.register(f, ts, b)["layout"]
    for t, (ex, ey, ez) in zip(ts, MOSAIC_ERRORS):
        ea, eb, ec = a["tiles"][t.path], b["tiles"][t.path], c["tiles"][t.path]
        assert abs(ea["dx"] - ex * MOSAIC_PX) < 0.25 and abs(ea["dy"] - ey * MOSAIC_PX) < 0.25 and ea["dz"] == ez, (t.name, ea)
        assert abs(eb["dx"] - ex * MOSAIC_PX) < 0.1 and abs(eb["dy"] - ey * MOSAIC_PX) < 0.1, (t.name, eb)
        assert abs(eb["dx"] - ec["dx"]) < 0.02 and abs(eb["dy"] - ec["dy"]) < 0.02 and eb["dz"] == ec["dz"], (t.name, eb, ec)


def test_a_repeated_tile_in_the_order_counts_once_at_its_first_place(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
        p0, p1 = ts[0].path, ts[1].path
        g = M.geometry(ts, {"order": [p1, p0, p1], "seams": "order"})
        a = M.compose(f, ts, {"order": [p1, p0, p1], "seams": "order"}, planes=[5])[0]
        b = M.compose(f, ts, {"order": [p1, p0], "seams": "order"}, planes=[5])[0]
    assert g["order"][:2] == [p1, p0] and g["order"].count(p1) == 1
    assert np.array_equal(a, b, equal_nan=True)


def test_compose_takes_planes_in_any_order(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
        m = M.compose(f, ts, {}, planes=[5, 3, 5])
        s3, s5 = M.compose(f, ts, {}, planes=[3])[0], M.compose(f, ts, {}, planes=[5])[0]
    assert np.array_equal(m[0], s5, equal_nan=True) and np.array_equal(m[1], s3, equal_nan=True) and np.array_equal(m[2], s5, equal_nan=True)


def test_tiff_bytes_counts_the_planes_it_is_given(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
    g = M.geometry(ts)
    assert M.tiff_bytes(ts, {}, 1, [3, 4, 5]) == 3 * g["width"] * g["height"] * 4


def test_a_hand_edited_layout_with_odd_values_opens(mos):
    with MescFile(mos) as f:
        ts = M.tiles(f)
    lay = {"tiles": {ts[0].path: {"dx": None, "dy": "abc", "dz": "nan"}, ts[1].path: "junk"}, "order": "x"}
    g = M.geometry(ts, lay)
    assert g["place"][ts[0].path]["z0"] == 0 and len(g["place"]) == 6
    assert M.geometry(ts, {"tiles": [1, 2]})["width"] == M.geometry(ts)["width"]


def test_a_nan_stage_position_leaves_that_tile_out(mos, tmp_path):
    def nan_pos(u):
        a = u["MUnit_3"].attrs
        xml = bytes(a["MeasurementParamsXML"]).decode("latin-1")
        for ax in ("VirtX", "SlowX"):                          # absolute and from the zero: neither usable
            i = xml.index(f'id="{ax}" value="') + len(f'id="{ax}" value="')
            xml = xml[:i] + "nan" + xml[xml.index('"', i):]
        a["MeasurementParamsXML"] = np.frombuffer(xml.encode("latin-1"), dtype=np.uint8)
    p = _edited(mos, tmp_path / "nan.mesc", nan_pos)
    with MescFile(p) as f:
        ts = M.tiles(f)
    assert "MUnit_3" not in [t.name for t in ts] and len(ts) == 5
    M.geometry(ts)


def test_a_tile_without_depth_among_tiles_with_it_is_said(mos, tmp_path):
    lay = {f"MUnit_{i}": -27200.0 for i in range(5)}         # MUnit_5 carries no geometry
    p = _edited(mos, tmp_path / "half.mesc", lambda u: _geom_z(u, lay))
    with MescFile(p) as f:
        ts = M.tiles(f)
    g = M.geometry(ts)
    assert g["z_um"] is None and g["warnings"] and "MUnit_5" in g["warnings"][0]
    assert M.geometry(ts, {"tiles": {ts[5].path: {"hidden": True}}})["z_um"] == pytest.approx(-27200.0)


def test_a_stack_without_the_axis_offset_takes_no_depth_from_its_centre(mos, tmp_path):
    # GeomTransTransl without ZAxisConversion…Offset is the stack's CENTRE: taken for slice 0 it put every
    # slice half a stack off; such a stack has no z0 at all
    def centre_only(u):
        for i in range(6):
            u[f"MUnit_{i}"].attrs["GeomTransTransl"] = np.array([0.0, 0.0, -27100.0])
    p = _edited(mos, tmp_path / "centre.mesc", centre_only)
    with MescFile(p) as f:
        assert all(u.z0_um is None for u in f.units())
