"""The engine over a recording that is not a .mesc: a MescFile subclass over another HDF5 layout.

The CIP playground serves frames straight from its master file, stored as (raw − 786) / 2 with a
conversion of 2. If the subclass hook works, every route answers with the SAME bytes as the engine
over the equivalent .mesc — same pixels, same reader units — and nothing .mesc-only breaks."""
from __future__ import annotations

import json

import h5py
import numpy as np
import pytest

from mesc_io import MescFile
from mesc_io.engine import Engine
from mesc_io.reader import Channel, Unit

from test_engine import SPOT

N, H, W = 12, 8, 10


def _raw(seed=3):
    return (1000 + np.random.RandomState(seed).randint(0, 400, (N, H, W))).astype(np.uint16)


def _mesc(path, raw):
    with h5py.File(path, "w") as f:
        u = f.create_group("MSession_0").create_group("MUnit_0")
        u.create_dataset("Channel_0", data=raw)
        u.attrs["Channel_0_Conversion_ConversionLinearOffset"] = -786.0
        u.attrs["Channel_0_Conversion_ConversionLinearScale"] = 1.0
        u.attrs["XAxisConversionConversionLinearScale"] = 0.5
        u.attrs["ZAxisConversionConversionLinearScale"] = 16.0
    return path


def _toy(path, raw):
    """Another layout: frames/<unit>/<channel>, stored halved, the conversion on the dataset."""
    with h5py.File(path, "w") as f:
        d = f.create_dataset("frames/MUnit_0/Channel_0", data=((raw.astype(np.int32) - 786) // 2).astype(np.uint16))
        d.attrs["conversion"], d.attrs["offset"] = 2.0, 0.0
        f["frames/MUnit_0"].attrs["note"] = "toy layout"
        f["frames/MUnit_0"].attrs["is_ignored"] = np.False_         # a numpy bool, as a master has
        f["frames/MUnit_0"].attrs["n_frames"] = np.int64(N)
    return path


class ToyRecording(MescFile):
    def units(self):
        d = self._f["frames/MUnit_0/Channel_0"]
        ch = Channel(index=0, name="Channel_0", offset=float(d.attrs["offset"]), scale=float(d.attrs["conversion"]))
        return [Unit(name="MUnit_0", session="MSession_0", n_frames=N, height=H, width=W, dtype="uint16",
                     frame_rate_hz=1000 / 16.0, pixel_size_um=0.5, comment="", channels=[ch])]

    def _dataset(self, u, ch):
        return self._f[f"frames/{u.name}/{ch.name}"]

    def unit_attributes(self, unit_path):
        return dict(self._f["frames/MUnit_0"].attrs) if unit_path == "MSession_0/MUnit_0" else None


ROUTES = ["/api/frame/MSession_0/MUnit_0/0/3?n=4", "/api/frame/MSession_0/MUnit_0/0/0?lo=1&hi=99",
          "/api/mean/MSession_0/MUnit_0/0", "/api/mean/MSession_0/MUnit_0/0?mode=max",
          "/api/pixel/MSession_0/MUnit_0/0?x=2&y=3", "/api/pixel/MSession_0/MUnit_0/0?x=2&y=3&i=5&n=3",
          "/api/traces/MSession_0/MUnit_0/0"]


@pytest.fixture
def pair(tmp_path):
    raw = _raw()
    raw[raw < 786] = 786                          # the toy floors at 0, as the master does
    raw = raw - ((raw - 786) % 2)                 # even distance from 786: halving loses nothing
    mesc = _mesc(tmp_path / "rec.mesc", raw)
    toy = _toy(tmp_path / "toy_master.h5", raw)
    rois = {"units": {"MSession_0/MUnit_0": [SPOT]}}
    (tmp_path / "a.json").write_text(json.dumps({"source": str(mesc), **rois}))
    (tmp_path / "b.json").write_text(json.dumps({"source": str(toy), **rois}))
    a = Engine(mesc, rois=tmp_path / "a.json")
    b = Engine(toy, rois=tmp_path / "b.json", opener=lambda: ToyRecording(toy))
    return a, b


def test_same_bytes_as_the_mesc(pair):
    a, b = pair
    for route in ROUTES:
        sa, _, ba = a.handle("GET", route)
        sb, _, bb = b.handle("GET", route)
        assert sa == sb == 200, (route, sa, sb, bb[:200])
        if route.startswith("/api/traces"):
            ja, jb = json.loads(ba), json.loads(bb)
            assert ja["traces"] == jb["traces"], route
        else:
            assert ba == bb, route


def test_the_comparison_can_fail(tmp_path):
    """Positive control: a toy whose conversion is wrong (1 instead of 2) must NOT match."""
    raw = _raw(); raw[raw < 786] = 786; raw = raw - ((raw - 786) % 2)
    mesc = _mesc(tmp_path / "rec.mesc", raw)
    toy = _toy(tmp_path / "toy.h5", raw)
    with h5py.File(toy, "a") as f:
        f["frames/MUnit_0/Channel_0"].attrs["conversion"] = 1.0
    a = Engine(mesc, rois=tmp_path / "a.json")
    b = Engine(toy, rois=tmp_path / "b.json", opener=lambda: ToyRecording(toy))
    r = "/api/pixel/MSession_0/MUnit_0/0?x=2&y=3"
    assert a.handle("GET", r)[2] != b.handle("GET", r)[2]


def test_mesc_only_routes_do_not_break(pair):
    _, b = pair
    s, _, body = b.handle("GET", "/api/file")
    d = json.loads(body)
    assert s == 200 and d["findings"] == [] and d["units"][0]["path"] == "MSession_0/MUnit_0"
    s, _, body = b.handle("GET", "/api/metadata/MSession_0/MUnit_0")
    m = json.loads(body)
    assert s == 200 and m["n_attributes"] == 3, m
    flat = {k: v for g in m["groups"].values() for k, v in g.items()}
    assert flat["is_ignored"] is False and flat["n_frames"] == N
    s, _, body = b.handle("GET", "/api/metadata/MSession_0/MUnit_9")
    assert "error" in json.loads(body)


def test_rois_round_trip_on_the_other_recording(pair):
    _, b = pair
    s, _, _ = b.handle("PUT", "/api/rois", json.dumps({"unit": "MSession_0/MUnit_0", "rois": [SPOT, dict(SPOT, name="b")]}).encode(),
                       {"Content-Type": "application/json"})
    assert s == 200
    got = json.loads(b.handle("GET", "/api/rois?unit=MSession_0%2FMUnit_0")[2])["rois"]
    assert [r["name"] for r in got] == ["a", "b"]
