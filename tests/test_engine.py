"""The engine without its server (mesc_io.engine): the same bytes as the viewer over HTTP, mountable elsewhere."""
from __future__ import annotations

import json
import socket
import threading
import urllib.request
from http.server import HTTPServer

import h5py
import numpy as np
import pytest

from mesc_io.engine import Engine
from mesc_io.viewer import _Handler, _BoundedCache


def _rec(path, seed=0, n=12, h=8, w=10):
    rng = np.random.RandomState(seed)
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0").create_group("MUnit_0")
        u.create_dataset("Channel_0", data=(1000 + rng.randint(0, 400, (n, h, w))).astype(np.uint16))
        u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = -786.0
        u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
        u.attrs["XAxisConversionConversionLinearScale"] = 0.5
        u.attrs["ZAxisConversionConversionLinearScale"] = 16.0
    return path


SPOT = {"name": "a", "kind": "rect", "points": [[1, 1], [4, 1], [4, 4], [1, 4]]}
ROUTES = ["/api/file", "/api/frame/MSession_0/MUnit_0/0/3?n=4", "/api/mean/MSession_0/MUnit_0/0",
          "/api/pixel/MSession_0/MUnit_0/0?x=2&y=3", "/api/rois?unit=MSession_0%2FMUnit_0",
          "/api/traces/MSession_0/MUnit_0/0", "/api/metadata/MSession_0/MUnit_0", "/api/no/such/route"]


@pytest.fixture
def standalone(tmp_path):
    rec = _rec(tmp_path / "rec.mesc")
    rois = tmp_path / "standalone_rois.json"
    rois.write_text(json.dumps({"source": str(rec), "units": {"MSession_0/MUnit_0": [SPOT]}}))
    _Handler.mesc_path, _Handler.rois_path, _Handler._cache = rec, rois, _BoundedCache()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    httpd = HTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield rec, f"http://127.0.0.1:{port}", tmp_path
    httpd.shutdown()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _norm(b: bytes) -> bytes:
    """The ROI file's path is in some replies; the two sides use different files on purpose."""
    try:
        d = json.loads(b)
    except ValueError:
        return b
    if isinstance(d, dict):
        d.pop("path", None)
    return json.dumps(d, sort_keys=True).encode()


def test_engine_gives_the_viewers_bytes(standalone):
    rec, base, tmp = standalone
    eng_rois = tmp / "engine_rois.json"
    eng_rois.write_text(json.dumps({"source": str(rec), "units": {"MSession_0/MUnit_0": [SPOT]}}))
    eng = Engine(rec, rois=eng_rois)
    for route in ROUTES:
        s1, b1 = _get(base + route)
        s2, _, b2 = eng.handle("GET", route)
        assert s1 == s2, route
        assert _norm(b1) == _norm(b2), route


def test_rois_saved_through_the_engine_come_back_and_land_in_its_file(tmp_path):
    rec = _rec(tmp_path / "rec.mesc")
    eng = Engine(rec, rois=tmp_path / "mine.json")
    s, _, b = eng.handle("PUT", "/api/rois", json.dumps({"unit": "MSession_0/MUnit_0", "rois": [SPOT]}).encode(),
                         {"Content-Type": "application/json"})
    assert s == 200 and json.loads(b)["saved"] == 1
    s, _, b = eng.handle("GET", "/api/rois?unit=MSession_0%2FMUnit_0")
    assert json.loads(b)["rois"][0]["points"] == SPOT["points"]
    assert json.loads((tmp_path / "mine.json").read_text())["units"]["MSession_0/MUnit_0"][0]["name"] == "a"


def test_two_engines_do_not_share_recording_rois_or_cache(tmp_path):
    a = Engine(_rec(tmp_path / "a.mesc", seed=1), rois=tmp_path / "a.json")
    b = Engine(_rec(tmp_path / "b.mesc", seed=2), rois=tmp_path / "b.json")
    a.handle("PUT", "/api/rois", json.dumps({"unit": "MSession_0/MUnit_0", "rois": [SPOT]}).encode())
    assert json.loads(b.handle("GET", "/api/rois?unit=MSession_0%2FMUnit_0")[2])["rois"] == []
    fa = a.handle("GET", "/api/frame/MSession_0/MUnit_0/0/0")[2]
    fb = b.handle("GET", "/api/frame/MSession_0/MUnit_0/0/0")[2]
    assert fa != fb                                        # different recordings, different frames
    assert a._cls._cache is not b._cls._cache and a._cls._lock is not b._cls._lock


def test_the_page_and_a_bad_method(tmp_path):
    eng = Engine(_rec(tmp_path / "rec.mesc"), rois=tmp_path / "r.json")
    s, h, body = eng.handle("GET", "/")
    assert s == 200 and h["Content-Type"].startswith("text/html") and b"<html" in body.lower()
    assert eng.handle("DELETE", "/api/rois")[0] == 405
