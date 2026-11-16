"""The public host API (0.6.7): `make_server(..., opener=, epochs=)`.

A host — the calcium pipeline's master launcher — used to set `_Handler`'s class attributes by
hand: a rename in mesc-io would have dropped its bands with no error, and two viewers in one
process would have shared one recording. Each server now gets its own handler class."""
import json
import shutil
import threading
import urllib.request

import pytest

from mesc_io import MescFile
from mesc_io import viewer as V


def _get(httpd, path):
    host, port = httpd.server_address[:2]
    with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=5) as r:
        return json.loads(r.read())


@pytest.fixture
def running():
    servers = []

    def start(*a, **k):
        httpd = V.make_server(*a, port=0, **k)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return httpd
    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


def test_two_viewers_in_one_process_keep_their_own_recording_and_bands(mesc, tmp_path, running):
    other = tmp_path / "other.mesc"
    shutil.copy(mesc, other)
    a = running(mesc, rois_path=tmp_path / "a_rois.json",
                epochs=lambda unit: [{"start": 1, "end": 4, "label": f"A {unit}"}])
    # b serves a "master" that is not a .mesc at its path: only the opener can read it
    b = running(tmp_path / "experiment_master.h5", rois_path=tmp_path / "b_rois.json",
                opener=lambda: MescFile(other),
                epochs=lambda unit: [{"start": 2, "end": 3, "label": "B", "kind": "moving"}])
    ea = _get(a, "/api/epochs/MSession_0/MUnit_0")["epochs"]
    eb = _get(b, "/api/epochs/MSession_0/MUnit_0")["epochs"]
    assert [e["label"] for e in ea] == ["A MSession_0/MUnit_0"]
    assert [(e["label"], e["kind"]) for e in eb] == [("B", "moving")]
    fa, fb = _get(a, "/api/file"), _get(b, "/api/file")
    assert fa["file"] == mesc.name and fb["file"] == "experiment_master.h5"
    assert len(fa["units"]) == len(fb["units"]) == 2          # b's units came through the opener
    assert a.RequestHandlerClass._cache is not b.RequestHandlerClass._cache
    # and the module's own handler was never touched
    assert V._Handler._epochs is None and V._Handler._opener is None


def test_without_a_host_there_are_no_bands(mesc, tmp_path, running):
    s = running(mesc, rois_path=tmp_path / "r.json")
    assert _get(s, "/api/epochs/MSession_0/MUnit_0") == {"epochs": []}


def test_an_unreadable_recording_fails_before_the_browser(tmp_path):
    with pytest.raises(Exception):
        V.make_server(tmp_path / "nope.mesc", port=0)

    def broken():
        raise OSError("master is on a disk that is not mounted")
    with pytest.raises(OSError, match="not mounted"):
        V.make_server(tmp_path / "experiment_master.h5", port=0, opener=broken)
