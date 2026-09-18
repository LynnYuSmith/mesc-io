#!/usr/bin/env python3
"""`mesc-io view` — look at a raw `.mesc` in the browser, with the numbers the file actually holds.

The lab has two tools and each is missing what the other has. The native Femtonics reader shows
the MOVIE — scrub it, wind the contrast, see the field before anything has been analysed — and
tells you almost nothing trustworthy about it. Our own report server shows everything about an
analysed master and cannot show you a raw recording at all, because by then the frames have been
through the pipeline.

This is the third thing: the movie, with the file's own truth attached. Frame rate per unit,
pixel size, the values the native reader would display, and the disagreements the file has with
itself — all from `mesc-io`, all read from the file's attributes rather than assumed.

    mesc-io view <recording.mesc> [--port 8020] [--no-browser]

Endpoints:
    GET  /api/file                          → units, rates, pixel sizes, comments, check findings
    GET  /api/frame/{unit}/{ch}/{i}         → PNG of one frame       (?lo=&hi= percentile window,
                                              ?n= average of n frames centred on i)
    GET  /api/mean/{unit}/{ch}              → PNG of the mean image  (?lo=&hi=)
    GET  /api/thumb/{unit}/{ch}             → small PNG of the mean image, for the unit list
    GET  /api/view                          → the saved view (unit, frame, zoom, …) or {}
    PUT  /api/view                          → replace the saved view (written beside the ROIs)
    GET  /api/trace/{unit}/{ch}?x=&y=&r=    → JSON time course of a disc, in reader units
    GET  /api/rois?unit=                    → that unit's ROI set (+ which units have any)
    PUT  /api/rois                          → replace ONE unit's set  <- {"unit": ..., "rois": [...]}
    POST /api/rois/copy                     → copy a unit's set onto another  <- {"from": ..., "to": ...}
    GET  /api/traces/{unit}/{ch}            → JSON: every ROI's time course, in ONE pass
    GET  /api/export/traces/{unit}/{ch}.csv → CSV, one column per ROI
    GET  /api/export/rois.json              → every unit's ROI set, as stored
    GET  /api/export/rois.zip?unit=         → that unit's ROIs as an ImageJ set, openable in Fiji
                                              and by our own pipeline, which reads exactly this format

ROIs belong to a UNIT. The field moves between areas and even between repeats of one area,
so a set drawn on MUnit_3 says nothing about MUnit_7; the store is keyed by unit path. A file
in the old shape (one flat list) is carried over onto the first unit and written back in the
new shape, with a line in the log saying so.

The `.mesc` is opened read-only and never written. ROIs live in a sidecar JSON of their own,
NOT beside the raw file: raw data is not ours to add files to.
Bound to 127.0.0.1.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from . import MescFile
from .check import check as mesc_check

PAGE = Path(__file__).resolve().parent / "viewer.html"


def _in_polygon(pts: np.ndarray, h: int, w: int) -> np.ndarray:
    """Even-odd ray casting, vectorised over the whole frame. NumPy only.

    This replaces ``matplotlib.path.Path.contains_points``. A lab tool that has to run on a
    colleague's machine should not pull in a plotting library to answer whether a pixel is
    inside a polygon — every extra dependency is one more way for "it does not start" to
    happen on someone else's laptop. Verified against matplotlib on random polygons; see
    ``tests/test_viewer_geometry.py``.
    """
    yy, xx = np.mgrid[0:h, 0:w]
    x = xx.astype(float)
    y = yy.astype(float)
    inside = np.zeros((h, w), dtype=bool)
    x0, y0 = pts[-1]
    for x1, y1 in pts:
        # does the horizontal ray from the pixel cross the edge (x0,y0)-(x1,y1)
        straddles = ((y0 > y) != (y1 > y))
        with np.errstate(divide="ignore", invalid="ignore"):
            xkreuz = (x1 - x0) * (y - y0) / np.where(y1 != y0, y1 - y0, np.nan) + x0
        inside ^= straddles & (x < xkreuz)
        x0, y0 = x1, y1
    return inside


def _mask_of(roi: dict, h: int, w: int) -> np.ndarray:
    """Boolean mask for one ROI. Everything is stored as a polygon, including the disc a
    single click makes — one shape means one code path here and one format on export."""
    pts = np.asarray(roi.get("points", []), dtype=float)
    if len(pts) < 3:
        raise ValueError(f"ROI {roi.get('name')!r} has fewer than three points")
    mask = _in_polygon(pts, h, w)
    if not mask.any():                      # a shape thinner than a pixel still has a centre
        cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
        yi, xi = int(round(cy)), int(round(cx))
        if 0 <= yi < h and 0 <= xi < w:
            mask[yi, xi] = True
    return mask


def _png(img: np.ndarray, lo_pct: float, hi_pct: float) -> bytes:
    """8-bit PNG of one frame, windowed on percentiles of ITS OWN values.

    Percentiles rather than min/max: a single hot pixel otherwise drives the whole frame black,
    which is the usual reason a field "looks empty" in a viewer.
    """
    a = np.asarray(img, dtype=np.float32)
    lo, hi = np.percentile(a, [lo_pct, hi_pct])
    if hi <= lo:
        hi = lo + 1.0
    b = np.clip((a - lo) / (hi - lo), 0, 1)
    return _png_grau((b * 255).astype(np.uint8))


def _png_grau(a: np.ndarray) -> bytes:
    """8-bit grayscale PNG, written by hand. Stdlib only.

    Pillow was the only other reason this viewer needed a dependency beyond numpy. A greyscale
    PNG is a fixed header, one IHDR, one zlib-compressed IDAT with a filter byte per row, and
    an IEND — forty lines against a wheel that fails to build often enough to matter on a
    lab machine. The tests do not claim byte-identity with Pillow — zlib settings differ, so
    the bytes are not the same — they claim what matters: Pillow decodes this PNG back to
    exactly the pixels that went in.
    """
    import struct
    import zlib

    h, w = a.shape
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(kind: bytes, daten: bytes) -> bytes:
        return (struct.pack(">I", len(daten)) + kind + daten
                + struct.pack(">I", zlib.crc32(kind + daten) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


class _Handler(BaseHTTPRequestHandler):
    mesc_path: Path = None          # set by serve()
    rois_path: Path = None          # ""
    _lock = threading.Lock()
    _cache = {}

    # -- plumbing ---------------------------------------------------------
    def log_message(self, fmt, *args):      # quiet: one line per run, not per request
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code: int = 200):
        self._send(json.dumps(payload).encode(), "application/json", code)

    def _fail(self, exc: Exception, code: int = 400):
        self._json({"error": f"{type(exc).__name__}: {exc}"}, code)

    def _file(self) -> MescFile:
        return MescFile(self.mesc_path)

    # -- routes -----------------------------------------------------------
    def do_GET(self):                                        # noqa: N802
        url = urlparse(self.path)
        q = parse_qs(url.query)
        parts = [p for p in url.path.split("/") if p]
        try:
            if not parts or parts == ["index.html"]:
                return self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            if parts == ["favicon.ico"]:
                # Answer it rather than 404: an unanswered favicon is a console error, and a
                # console error is exactly what the headless check watches for.
                return self._send(b"", "image/x-icon", 204)
            if parts[:2] == ["api", "file"]:
                return self._json(self._describe())
            # A unit is addressed by its path, `MSession_0/MUnit_0`, which contains a slash —
            # so the unit is everything between the verb and the trailing numbers, not one
            # segment. Splitting naively made every request for a real unit a 404, and the
            # page showed a blank field with nothing in the log.
            if parts[:2] == ["api", "frame"] and len(parts) >= 5:
                return self._frame("/".join(parts[2:-2]), int(parts[-2]), int(parts[-1]), q)
            if parts[:2] == ["api", "mean"] and len(parts) >= 4:
                return self._mean("/".join(parts[2:-1]), int(parts[-1]), q)
            if parts[:2] == ["api", "thumb"] and len(parts) >= 4:
                return self._thumb("/".join(parts[2:-1]), int(parts[-1]), q)
            if parts[:2] == ["api", "view"]:
                return self._json({"view": self._load_view(), "path": str(self.view_path)})
            if parts[:2] == ["api", "trace"] and len(parts) >= 4:
                return self._trace("/".join(parts[2:-1]), int(parts[-1]), q)
            if parts[:2] == ["api", "rois"]:
                unit = (q.get("unit") or [""])[0]
                store = self._load_store()
                return self._json({"unit": unit, "rois": store.get(unit, []) if unit else [],
                                   "units_with_rois": {k: len(v) for k, v in store.items() if v},
                                   "path": str(self.rois_path)})
            if parts[:2] == ["api", "traces"] and len(parts) >= 4:
                return self._json(self._roi_traces("/".join(parts[2:-1]), int(parts[-1])))
            if parts[:3] == ["api", "export", "rois.json"]:
                body = json.dumps({"source": str(self.mesc_path), "units": self._load_store()},
                                  indent=2).encode()
                return self._download(body, "application/json", "rois.json")
            if parts[:3] == ["api", "export", "rois.zip"]:
                return self._export_imagej((q.get("unit") or [""])[0])
            if parts[:3] == ["api", "export", "traces"] and len(parts) >= 5:
                return self._export_csv("/".join(parts[3:-1]), int(parts[-1].split(".")[0]))
            self._json({"error": f"no route for {url.path}"}, 404)
        except Exception as exc:                             # noqa: BLE001
            self._fail(exc)

    def do_PUT(self):                                        # noqa: N802
        url = urlparse(self.path)
        try:
            parts = [p for p in url.path.split("/") if p]
            if parts[:2] == ["api", "view"]:
                n = int(self.headers.get("Content-Length", 0))
                view = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(view, dict):
                    raise ValueError("expected a JSON object")
                self._save_view(view)
                return self._json({"saved": True, "path": str(self.view_path)})
            if parts[:2] != ["api", "rois"]:
                return self._json({"error": "no route"}, 404)
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            unit, rois = payload.get("unit"), payload.get("rois", [])
            if not unit or not isinstance(unit, str):
                raise ValueError("expected {'unit': 'MSession_0/MUnit_3', 'rois': [...]}")
            if not isinstance(rois, list):
                raise ValueError("expected {'rois': [...]}")
            store = self._load_store()
            if rois:
                store[unit] = rois
            else:
                store.pop(unit, None)
            self._save_store(store)
            self._json({"unit": unit, "saved": len(rois), "path": str(self.rois_path)})
        except Exception as exc:                             # noqa: BLE001
            self._fail(exc)

    def do_POST(self):                                       # noqa: N802
        url = urlparse(self.path)
        try:
            if [p for p in url.path.split("/") if p] != ["api", "rois", "copy"]:
                return self._json({"error": "no route"}, 404)
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            src, dst = payload.get("from"), payload.get("to")
            if not (src and dst) or src == dst:
                raise ValueError("expected {'from': <unit>, 'to': <another unit>}")
            store = self._load_store()
            if not store.get(src):
                raise ValueError(f"{src} has no ROIs to copy")
            store[dst] = [dict(r) for r in store[src]]
            self._save_store(store)
            self._json({"unit": dst, "copied": len(store[dst]), "from": src})
        except Exception as exc:                             # noqa: BLE001
            self._fail(exc)

    # -- the ROI store: {unit path: [roi, ...]} ---------------------------------
    def _load_store(self) -> dict:
        if not self.rois_path.exists():
            return {}
        try:
            data = json.loads(self.rois_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        units = data.get("units")
        if isinstance(units, dict):
            return {k: v for k, v in units.items() if isinstance(v, list)}
        # the old shape: one flat list for the whole file. Carry it onto the first unit rather
        # than lose it, and say so -- it may or may not be the unit it was drawn on.
        legacy = data.get("rois")
        if isinstance(legacy, list) and legacy:
            with self._file() as f:
                first = f.units()[0].path
            print(f"  {self.rois_path.name}: {len(legacy)} ROIs in the old file-wide shape, "
                  f"carried onto {first}; check they belong there", flush=True)
            store = {first: legacy}
            self._save_store(store)
            return store
        return {}

    def _load_rois(self, unit: str) -> list:
        return self._load_store().get(unit, [])

    def _save_store(self, store: dict):
        """Written through a temporary file and renamed: a crash mid-write would otherwise
        leave a truncated set, and the set is the only record of hand-drawn work."""
        self.rois_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.rois_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"source": str(self.mesc_path), "units": store}, indent=2))
        tmp.replace(self.rois_path)

    # -- the view: where you were looking, saved by itself -------------------
    # Same idea as pupil-monitor's sidecar and the runner's session file: no button. Unit,
    # channel, frame, averaging window, contrast, zoom, trace mode -- written on every change
    # so reopening the file puts you back where you were.
    @property
    def view_path(self) -> Path:
        return self.rois_path.with_name(self.rois_path.stem.replace("_rois", "") + "_view.json")

    def _load_view(self):
        if not self.view_path.exists():
            return {}
        try:
            return json.loads(self.view_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_view(self, view):
        self.view_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.view_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"source": str(self.mesc_path), **view}, indent=1))
        tmp.replace(self.view_path)

    def _download(self, body: bytes, ctype: str, filename: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _roi_traces(self, unit: str, ch: int):
        """Every ROI's time course from ONE pass over the recording.

        One pass, not one per ROI: the file is gigabytes, and reading it once per ROI would
        turn a dozen boutons into a dozen full reads of the same bytes.
        """
        rois = self._load_rois(unit)
        with self._file() as f:
            u = f.unit(unit)
            if not rois:
                return {"unit": u.path, "channel": ch, "frame_rate_hz": u.frame_rate_hz,
                        "names": [], "traces": []}
            masks = [_mask_of(r, u.height, u.width) for r in rois]
            areas = [int(m.sum()) for m in masks]
            acc = [[] for _ in masks]
            for block in f.iter_frames(unit, channel=ch, block=500, reader_units=True):
                flat = block.reshape(len(block), -1)
                for k, m in enumerate(masks):
                    acc[k].append(flat[:, m.ravel()].mean(axis=1))
            traces = [np.concatenate(a) for a in acc]
        return {"unit": u.path, "channel": ch, "frame_rate_hz": u.frame_rate_hz,
                "names": [r.get("name", f"roi{i}") for i, r in enumerate(rois)],
                "areas_px": areas,
                "traces": [[round(float(v), 2) for v in t] for t in traces]}

    def _export_csv(self, unit: str, ch: int):
        d = self._roi_traces(unit, ch)
        if not d["names"]:
            raise ValueError("no ROIs to export")
        fs = d["frame_rate_hz"] or 0.0
        head = ["frame", "time_s"] + list(d["names"])
        lines = [",".join(head)]
        n = len(d["traces"][0])
        for i in range(n):
            row = [str(i), f"{i / fs:.4f}" if fs else ""]
            row += [f"{t[i]:.2f}" for t in d["traces"]]
            lines.append(",".join(row))
        name = f"{self.mesc_path.stem}_{unit.replace('/', '_')}_ch{ch}_traces.csv"
        self._download(("\n".join(lines) + "\n").encode(), "text/csv", name)

    def _export_imagej(self, unit: str):
        """One unit's ROI set as an ImageJ `.zip` — the format Fiji opens and our own pipeline
        reads, so a set drawn here can go straight into an analysis instead of being retyped."""
        import roifile
        if not unit:
            raise ValueError("say which unit: /api/export/rois.zip?unit=MSession_0/MUnit_3")
        rois = self._load_rois(unit)
        if not rois:
            raise ValueError(f"{unit} has no ROIs to export")
        out = io.BytesIO()
        made = []
        for i, r in enumerate(rois):
            pts = np.asarray(r.get("points", []), dtype=np.float32)
            ij = roifile.ImagejRoi.frompoints(pts)
            ij.name = str(r.get("name", f"roi{i}"))
            made.append(ij)
        import zipfile
        with zipfile.ZipFile(out, "w") as zf:
            for ij in made:
                zf.writestr(f"{ij.name}.roi", ij.tobytes())
        self._download(out.getvalue(), "application/zip",
                       f"{self.mesc_path.stem}_{unit.replace('/', '_')}_rois.zip")

    def _describe(self):
        key = (str(self.mesc_path), "describe")
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit
        out = self._describe_uncached()
        with self._lock:
            self._cache[key] = out
        return out

    def _describe_uncached(self):
        with self._file() as f:
            units = [{
                "path": u.path, "name": u.name, "session": u.session,
                "frames": u.n_frames, "height": u.height, "width": u.width,
                "frame_rate_hz": u.frame_rate_hz, "duration_s": u.duration_s,
                "pixel_size_um": u.pixel_size_um, "comment": u.comment,
                "channels": [c.name for c in u.channels],
                "stage_um": u.stage_um,
            } for u in f.units()]
        rep = mesc_check(self.mesc_path)
        return {"file": self.mesc_path.name, "path": str(self.mesc_path), "units": units,
                "findings": [{"level": x.level, "code": x.code, "message": x.message,
                              "units": list(x.units)} for x in rep.findings]}

    @staticmethod
    def _window(q):
        return float(q.get("lo", ["1"])[0]), float(q.get("hi", ["99.5"])[0])

    def _frame(self, unit, ch, i, q):
        """One frame — or the mean of ``n`` frames centred on it.

        A single raw frame of a dim bouton is mostly shot noise; averaging a short window
        while scrubbing is what makes the structure visible without committing to the whole
        recording's mean. The window is clipped at the ends, never padded, so the first and
        last frames average fewer neighbours rather than borrowing invented ones.
        """
        n = max(1, int(float(q.get("n", ["1"])[0])))
        with self._file() as f:
            u = f.unit(unit)
            lo = max(0, i - n // 2)
            hi = min(u.n_frames, lo + n)
            lo = max(0, hi - n)
            block = f.read(unit, channel=ch, frames=slice(lo, hi), reader_units=True, max_gb=None)
            img = block[0] if n == 1 else block.mean(axis=0)
        self._send(_png(img, *self._window(q)), "image/png")

    def _thumb(self, unit, ch, q):
        """A mean image shrunk for the unit list. Block-mean downsample, numpy only.

        Built from 40 frames, not the 300 the full mean uses: at 96 px nobody can tell, and on
        a 30-unit file the list would otherwise wait on thirty 300-frame reads from the HDD.
        """
        key = (str(self.mesc_path), unit, ch, "thumb")
        with self._lock:
            img = self._cache.get(key)
        if img is None:
            with self._file() as f:
                u = f.unit(unit)
                idx = np.unique(np.linspace(0, u.n_frames - 1, min(40, u.n_frames)).astype(int))
                img = f.read(unit, channel=ch, frames=idx, reader_units=True, max_gb=None).mean(axis=0)
            with self._lock:
                self._cache[key] = img
        h, w = img.shape
        k = max(1, int(np.ceil(max(h, w) / 96)))
        hh, ww = (h // k) * k, (w // k) * k
        small = img[:hh, :ww].reshape(hh // k, k, ww // k, k).mean(axis=(1, 3))
        self._send(_png(small, *self._window(q)), "image/png")

    def _mean_image(self, unit, ch):
        key = (str(self.mesc_path), unit, ch)
        with self._file() as f:
            u = f.unit(unit)
            idx = np.unique(np.linspace(0, u.n_frames - 1, min(300, u.n_frames)).astype(int))
            img = f.read(unit, channel=ch, frames=idx, reader_units=True,
                         max_gb=None).mean(axis=0)
        with self._lock:
            self._cache[key] = img
        return img

    def _mean(self, unit, ch, q):
        key = (str(self.mesc_path), unit, ch)
        with self._lock:
            img = self._cache.get(key)
        if img is None:
            img = self._mean_image(unit, ch)
        self._send(_png(img, *self._window(q)), "image/png")

    def _trace(self, unit, ch, q):
        """The time course of a small disc — click a bouton, see whether it does anything.

        Streamed unit by unit rather than read whole: a recording is gigabytes and this has to
        answer while someone is still looking at the screen.
        """
        x, y = int(float(q["x"][0])), int(float(q["y"][0]))
        r = int(float(q.get("r", ["3"])[0]))
        with self._file() as f:
            u = f.unit(unit)
            yy, xx = np.mgrid[0:u.height, 0:u.width]
            mask = (yy - y) ** 2 + (xx - x) ** 2 <= r * r
            if not mask.any():
                raise ValueError(f"({x}, {y}) is outside the {u.width}x{u.height} field")
            out = []
            for block in f.iter_frames(unit, channel=ch, block=500, reader_units=True):
                out.append(block[:, mask].mean(axis=1))
            trace = np.concatenate(out)
        return self._json({"unit": u.path, "channel": ch, "x": x, "y": y, "r": r,
                           "frame_rate_hz": u.frame_rate_hz,
                           "values": [round(float(v), 2) for v in trace]})


PRIVATE_FLAGS = {          # how each browser is asked for a window that remembers nothing
    "Google Chrome": "--incognito",
    "Brave Browser": "--incognito",
    "Microsoft Edge": "--inprivate",
    "Chromium": "--incognito",
    "Firefox": "-private-window",
}


def open_private(url: str) -> str:
    """Open *url* in a private window. Returns what actually happened, in words.

    Private on purpose: the viewer is opened dozens of times a day against different
    recordings, and a normal window turns that into a history full of `127.0.0.1:8020` entries
    that all look the same and none of which can be gone back to. A private window also starts
    with an empty page state every time, so a stale cached page cannot be mistaken for the
    current recording.

    Nothing of value is lost by it: the regions live in a file on disk, served by this process,
    not in the browser's storage.

    Falls back to the default browser, and SAYS so — a viewer that silently opens the wrong
    kind of window is worse than one that tells you it could not find Chrome.
    """
    if sys.platform == "darwin":
        for app, flag in PRIVATE_FLAGS.items():
            if not Path(f"/Applications/{app}.app").is_dir():
                continue
            try:
                subprocess.Popen(["open", "-na", app, "--args", flag, url],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"{app}, private window"
            except OSError:
                continue
        # Safari has no command-line switch for a private window, so it is not attempted:
        # opening a normal Safari window while claiming privacy would be the worst outcome.
        webbrowser.open(url)
        return "default browser (no Chrome/Firefox/Edge found — NOT private)"
    for exe, flag in (("google-chrome", "--incognito"), ("chromium", "--incognito"),
                      ("firefox", "-private-window")):
        try:
            subprocess.Popen([exe, flag, url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"{exe}, private window"
        except OSError:
            continue
    webbrowser.open(url)
    return "default browser (NOT private)"


def serve(mesc_path: Path, port: int = 8020, open_browser: bool = True,
          rois_path: Path = None) -> None:
    _Handler.mesc_path = Path(mesc_path)
    # Beside the working directory, not beside the recording: raw data is not ours to add
    # files to, and the disk it lives on is often read-only or simply not ours.
    _Handler.rois_path = Path(rois_path) if rois_path else Path.cwd() / f"{Path(mesc_path).stem}_rois.json"
    with MescFile(mesc_path) as f:                       # fail here, not in the browser
        n = len(f.units())
    # Threaded, and it matters: on a 30-unit recording the page asks for 30 thumbnails at once
    # and Chrome opens six connections for them. A single-threaded server with its five-deep
    # backlog answered the first, queued four, and REFUSED the rest -- the page sat blank and
    # curl got "connection refused" while the process was busy at 65 % CPU. Each request opens
    # its own MescFile, so there is no shared handle to protect.
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"  {Path(mesc_path).name}: {n} units  →  {url}   (ctrl-c to stop)")
    if open_browser:
        def _launch():
            print(f"  opening: {open_private(url)}", flush=True)
        threading.Timer(0.6, _launch).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mesc", type=Path)
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--rois", type=Path, default=None,
                    help="where the ROI set lives (default: ./<name>_rois.json)")
    a = ap.parse_args()
    if not a.mesc.exists():
        print(f"  not found: {a.mesc}")
        return 1
    serve(a.mesc, a.port, not a.no_browser, a.rois)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
