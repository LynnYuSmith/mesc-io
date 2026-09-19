"""The viewer's server, spoken to over HTTP on a synthetic recording.

The page is looked at in a real browser (see docs/viewer_design.md); what a test can hold
still is the server's side of the second layout: frames averaged over a window, the view that
saves itself, the thumbnail for the unit list, and the stage position read off the file.
"""
from __future__ import annotations

import json
import socket
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import h5py
import numpy as np
import pytest

from mesc_io import MescFile
from mesc_io.viewer import _Handler

OFFSET = -786.0
STAGE_XML = ('<?xml version="1.0"?><Params><AxisControl><snapshot>'
             '<axis attribute="AttributePosition" id="VirtX" value="915.0"/>'
             '<axis attribute="AttributePosition" id="VirtY" value="3671.0"/>'
             '<axis attribute="AttributePosition" id="VirtZ" value="-9.0"/>'
             '<axis attribute="AttributeRelativePosition" id="SlowX" value="80.0"/>'
             '</snapshot></AxisControl><param name="µm" value="1"/></Params>')


@pytest.fixture
def recording(tmp_path):
    """Ten frames: pixel value = frame index, plus one bright column that walks with the frame,
    so an average is checkable by hand AND differs in shape from any single frame."""
    path = tmp_path / "rec.mesc"
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0").create_group("MUnit_0")
        n, h, w = 10, 6, 8
        data = (np.arange(n, dtype=np.uint16)[:, None, None] * np.ones((h, w), dtype=np.uint16)
                + 1000)
        for k in range(n):
            data[k, :, k % w] += 500
        u.create_dataset("Channel_0", data=data)
        u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = OFFSET
        u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
        u.attrs["ZAxisConversionConversionLinearScale"] = 16.0
        u.attrs["XAxisConversionConversionLinearScale"] = 0.5
        u.attrs["Comment"] = np.frombuffer(b"area1 135deg\0", dtype=np.uint8)
        # the µ sign is why the block must be read as latin-1
        u.attrs["MeasurementParamsXML"] = np.frombuffer(STAGE_XML.encode("latin-1"), dtype=np.uint8)
    return path


@pytest.fixture
def server(recording, tmp_path):
    _Handler.mesc_path = recording
    _Handler.rois_path = tmp_path / "rec_rois.json"
    _Handler._cache = {}
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = HTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read(), r.headers.get("Content-Type", "")


def get_json(url):
    body, _ = get(url)
    return json.loads(body)


def put_json(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="PUT",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


# --- the reader: stage position -----------------------------------------------------------

def test_the_stage_position_is_read_off_the_file_as_latin1(recording):
    with MescFile(recording) as f:
        u = f.unit("MSession_0/MUnit_0")
    assert u.stage_um == {"x": 915.0, "y": 3671.0, "z": -9.0}


def test_a_file_without_the_xml_says_none_not_zero(tmp_path):
    path = tmp_path / "bare.mesc"
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0").create_group("MUnit_0")
        u.create_dataset("Channel_0", data=np.zeros((2, 4, 4), dtype=np.uint16))
    with MescFile(path) as f:
        assert f.unit("MSession_0/MUnit_0").stage_um is None


def test_describe_carries_the_stage_position(server):
    d = get_json(server + "/api/file")
    assert d["units"][0]["stage_um"] == {"x": 915.0, "y": 3671.0, "z": -9.0}


# --- averaged frames ------------------------------------------------------------------------

def test_a_window_changes_the_frame_and_answers_as_png(server):
    """Each frame paints against its own percentiles, so a PNG cannot show the average's
    LEVEL — that arithmetic is pinned by the slice test below. What it can show is shape: one
    bright column in a raw frame, four half-bright ones in a four-frame average."""
    body1, ct = get(server + "/api/frame/MSession_0/MUnit_0/0/9?n=1&lo=0&hi=100")
    body4, _ = get(server + "/api/frame/MSession_0/MUnit_0/0/9?n=4&lo=0&hi=100")
    assert ct.startswith("image/png")
    assert body1 != body4, "an averaging window changed nothing"


def test_the_window_is_clipped_at_the_ends_never_padded(recording):
    """Ask the handler's slice logic directly: at i=0 with n=8 the window is frames 0..7, not
    -4..3 (which would wrap in numpy and average the END of the recording into the start)."""
    with MescFile(recording) as f:
        u = f.unit("MSession_0/MUnit_0")
        n, i = 8, 0
        lo = max(0, i - n // 2); hi = min(u.n_frames, lo + n); lo = max(0, hi - n)
        assert (lo, hi) == (0, 8)
        n, i = 8, 9
        lo = max(0, i - n // 2); hi = min(u.n_frames, lo + n); lo = max(0, hi - n)
        assert (lo, hi) == (2, 10)
        block = f.read("MSession_0/MUnit_0", frames=slice(lo, hi), reader_units=True)
        # frame k is k + 1000 + OFFSET in reader units with one column of 8 raised by 500;
        # the mean over frames 2..9 is 5.5 + 1000 + OFFSET + 500/8
        assert block.mean() == pytest.approx(1000 + 5.5 + OFFSET + 500 / 8)


def test_n_below_one_is_treated_as_one(server):
    a, _ = get(server + "/api/frame/MSession_0/MUnit_0/0/3?n=0")
    b, _ = get(server + "/api/frame/MSession_0/MUnit_0/0/3?n=1")
    assert a == b


# --- the thumbnail ------------------------------------------------------------------------

def test_the_thumbnail_is_a_png_no_wider_than_96(server):
    body, ct = get(server + "/api/thumb/MSession_0/MUnit_0/0")
    assert ct.startswith("image/png")
    # IHDR: width at bytes 16..20, height 20..24
    w = int.from_bytes(body[16:20], "big"); h = int.from_bytes(body[20:24], "big")
    assert w <= 96 and h <= 96 and w > 0


# --- the view that saves itself -----------------------------------------------------------

def test_the_view_round_trips_and_lands_beside_the_rois(server, tmp_path):
    assert get_json(server + "/api/view")["view"] == {}
    view = {"unit": "MSession_0/MUnit_0", "frame": 350, "avg": 8, "zoom": {"x": 20, "y": 30, "w": 60, "h": 50},
            "traceMode": "overlay", "shown": {"roi1": False}}
    r = put_json(server + "/api/view", view)
    assert r["saved"] is True
    assert Path(r["path"]) == tmp_path / "rec_view.json"
    got = get_json(server + "/api/view")["view"]
    for k, v in view.items():
        assert got[k] == v
    assert got["source"].endswith("rec.mesc")
    assert not list(tmp_path.glob("*.tmp")), "the atomic write left its temp file"


def test_a_non_object_view_is_refused(server):
    req = urllib.request.Request(server + "/api/view", data=b"[1,2]", method="PUT",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


def test_a_corrupt_view_file_reads_as_empty(server, tmp_path):
    (tmp_path / "rec_view.json").write_text("{not json")
    assert get_json(server + "/api/view")["view"] == {}


# --- ROIs belong to a unit ----------------------------------------------------------------

def post_json(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


SPOT = {"name": "roi1", "points": [[3, 2], [4, 2], [4, 3], [3, 3]]}


@pytest.fixture
def two_unit_server(recording, tmp_path):
    with h5py.File(recording, "a") as f:
        src = f["MSession_0/MUnit_0"]
        dst = f["MSession_0"].create_group("MUnit_1")
        dst.create_dataset("Channel_0", data=src["Channel_0"][:])
        for k, v in src.attrs.items():
            dst.attrs[k] = v
    _Handler.mesc_path = recording
    _Handler.rois_path = tmp_path / "rec_rois.json"
    _Handler._cache = {}
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = HTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def test_a_set_saved_on_one_unit_is_not_seen_from_another(two_unit_server):
    s = two_unit_server
    put_json(s + "/api/rois", {"unit": "MSession_0/MUnit_0", "rois": [SPOT]})
    assert get_json(s + "/api/rois?unit=MSession_0/MUnit_0")["rois"] == [SPOT]
    assert get_json(s + "/api/rois?unit=MSession_0/MUnit_1")["rois"] == []
    assert get_json(s + "/api/rois?unit=MSession_0/MUnit_1")["units_with_rois"] == {"MSession_0/MUnit_0": 1}


def test_traces_and_the_imagej_export_use_that_units_set(two_unit_server):
    s = two_unit_server
    put_json(s + "/api/rois", {"unit": "MSession_0/MUnit_0", "rois": [SPOT]})
    assert get_json(s + "/api/traces/MSession_0/MUnit_0/0")["names"] == ["roi1"]
    assert get_json(s + "/api/traces/MSession_0/MUnit_1/0")["names"] == []
    body, ct = get(s + "/api/export/rois.zip?unit=MSession_0/MUnit_0")
    assert ct.startswith("application/zip") and body[:2] == b"PK"
    with pytest.raises(urllib.error.HTTPError):
        get(s + "/api/export/rois.zip?unit=MSession_0/MUnit_1")


def test_copy_brings_one_units_set_onto_another(two_unit_server):
    s = two_unit_server
    put_json(s + "/api/rois", {"unit": "MSession_0/MUnit_0", "rois": [SPOT]})
    r = post_json(s + "/api/rois/copy", {"from": "MSession_0/MUnit_0", "to": "MSession_0/MUnit_1"})
    assert r["copied"] == 1
    got = get_json(s + "/api/rois?unit=MSession_0/MUnit_1")["rois"]
    assert got == [SPOT] and got is not SPOT
    # and they are independent afterwards
    put_json(s + "/api/rois", {"unit": "MSession_0/MUnit_1", "rois": []})
    assert get_json(s + "/api/rois?unit=MSession_0/MUnit_0")["rois"] == [SPOT]


def test_a_put_without_a_unit_is_refused(two_unit_server):
    req = urllib.request.Request(two_unit_server + "/api/rois", data=json.dumps({"rois": [SPOT]}).encode(),
                                 method="PUT", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


def test_the_old_file_wide_shape_is_shown_on_the_first_unit_but_not_written_on_read(two_unit_server, tmp_path, capsys, recording):
    side = tmp_path / "rec_rois.json"
    side.write_text(json.dumps({"source": str(recording), "rois": [SPOT]}))
    before = side.read_text()
    d = get_json(two_unit_server + "/api/rois?unit=MSession_0/MUnit_0")
    assert d["rois"] == [SPOT] and d["legacy"] is True
    assert side.read_text() == before, "a GET must never write the store"
    assert "old file-wide shape" in capsys.readouterr().out
    # the first save writes the new shape, without the marker
    put_json(two_unit_server + "/api/rois", {"unit": "MSession_0/MUnit_1", "rois": [SPOT]})
    saved = json.loads(side.read_text())
    assert saved["units"] == {"MSession_0/MUnit_0": [SPOT], "MSession_0/MUnit_1": [SPOT]}
    assert "_legacy" not in saved["units"]


def test_a_sidecar_drawn_on_another_recording_is_refused_loudly(two_unit_server, tmp_path, capsys):
    (tmp_path / "rec_rois.json").write_text(json.dumps({"source": "/elsewhere/other.mesc",
                                                         "units": {"MSession_0/MUnit_0": [SPOT]}}))
    assert get_json(two_unit_server + "/api/rois?unit=MSession_0/MUnit_0")["rois"] == []
    assert "was drawn on other.mesc" in capsys.readouterr().out


def test_a_malformed_roi_is_refused_on_put_not_at_trace_time(two_unit_server):
    for bad in ([{"name": "x", "points": [[1, 1], [2, 2]]}],          # 2 points
                [{"name": "x", "points": [[1, 1], [2, 2], [3]]}],      # a 1-tuple
                [{"name": "x", "points": [[1, 1], [2, 2], ["a", 3]]}], # not a number
                ["not a dict"]):
        req = urllib.request.Request(two_unit_server + "/api/rois",
                                     data=json.dumps({"unit": "MSession_0/MUnit_0", "rois": bad}).encode(),
                                     method="PUT", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == 400


def test_the_averaging_window_is_capped_and_a_frame_out_of_range_is_refused(server):
    from mesc_io.viewer import MAX_AVG_FRAMES
    a, _ = get(server + f"/api/frame/MSession_0/MUnit_0/0/5?n={MAX_AVG_FRAMES}")
    b, _ = get(server + "/api/frame/MSession_0/MUnit_0/0/5?n=100000")
    assert a == b, "n above the cap must behave as the cap, not read the whole recording"
    for i in (-1, 10, 999):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(server + f"/api/frame/MSession_0/MUnit_0/0/{i}")
        assert e.value.code == 400
    with pytest.raises(urllib.error.HTTPError):
        get(server + "/api/pixel/MSession_0/MUnit_0/0?x=1&y=1&i=10")


def test_traces_carry_dff_only_when_the_file_states_a_rate(two_unit_server, tmp_path, recording):
    put_json(two_unit_server + "/api/rois", {"unit": "MSession_0/MUnit_0", "rois": [SPOT]})
    d = get_json(two_unit_server + "/api/traces/MSession_0/MUnit_0/0")
    assert d["dff"] is not None and d["params"]["bg_coef"] == 0.8 and d["dff_unavailable"] is None
    # strip the rate: raw traces still come, dF/F does not, and the reason is stated
    with h5py.File(recording, "a") as f:
        del f["MSession_0/MUnit_0"].attrs["ZAxisConversionConversionLinearScale"]
    _Handler._cache = {}
    d = get_json(two_unit_server + "/api/traces/MSession_0/MUnit_0/0")
    assert d["traces"] and d["dff"] is None and "no frame rate" in d["dff_unavailable"]
    body, _ = get(two_unit_server + "/api/export/traces/MSession_0/MUnit_0/0.csv")
    assert b"_dff" not in body.split(b"\n")[0]


# --- the hover readout ------------------------------------------------------------------------

def test_pixel_reads_the_frame_window_in_reader_units(server):
    # frame 4, column 4 is the raised column (k % w == 4): value 1000 + 4 + 500 + OFFSET
    d = get_json(server + "/api/pixel/MSession_0/MUnit_0/0?x=4&y=2&i=4&n=1")
    assert d["value"] == pytest.approx(1000 + 4 + 500 + OFFSET)
    # a 3-frame window around frame 4 at column 4: only frame 4 has the raised column there
    d3 = get_json(server + "/api/pixel/MSession_0/MUnit_0/0?x=4&y=2&i=4&n=3")
    assert d3["value"] == pytest.approx(1000 + 4 + 500 / 3 + OFFSET, abs=0.01)   # the readout is rounded to 0.01


def test_pixel_of_the_mean_and_out_of_field(server):
    d = get_json(server + "/api/pixel/MSession_0/MUnit_0/0?x=0&y=0")
    assert "value" in d and "patch_mean" in d
    with pytest.raises(urllib.error.HTTPError):
        get(server + "/api/pixel/MSession_0/MUnit_0/0?x=99&y=0")
