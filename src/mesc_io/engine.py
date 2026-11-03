"""The viewer's engine without its HTTP server: mount it in another application.

``Engine(recording, rois=...)`` answers the same routes the viewer answers — ``/api/frame``, ``/api/mean``,
``/api/pixel``, ``/api/rois``, ``/api/traces``, ``/api/export/...``, ``/api/object``, ``/api/mosaic/...`` and the
page itself — as ``engine.handle(method, path, body=b"", headers=None) -> (status, headers, body)``. Another
server routes a prefix of its own (say ``/mesc/``) to it and hands back what it returns; the viewer's page can
then be served from that server too, under that prefix.

Nothing in the routes was rewritten for this: an Engine runs the viewer's own handler on a request held in
memory and keeps the reply in memory instead of writing it to a socket. So the standalone viewer and a mounted
engine give the same bytes for the same request — tested, not assumed (``tests/test_engine.py``). Each Engine
has its own ROI file, cache and locks, so one process can hold several recordings.
"""
from __future__ import annotations

import io
import threading
from email.message import Message
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import viewer as _viewer


class _Captured(_viewer._Handler):
    """The viewer's handler, fed from memory, replying into memory. No socket, no BaseHTTPRequestHandler init."""

    def __init__(self, method: str, path: str, body: bytes, headers: Optional[Dict[str, str]]):  # noqa: D107
        self.command = method
        self.path = path
        self.request_version = "HTTP/1.1"
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v
        if body and "Content-Length" not in self.headers:
            self.headers["Content-Length"] = str(len(body))
        self.rfile = io.BytesIO(body or b"")
        self.wfile = io.BytesIO()
        self._status = 200
        self._out_headers: Dict[str, str] = {}

    # the three calls the viewer's replies are made of
    def send_response(self, code, message=None):          # noqa: D401
        self._status = int(code)

    def send_header(self, keyword, value):
        self._out_headers[str(keyword)] = str(value)

    def end_headers(self):
        pass


class Engine:
    """One recording (and its ROI file) behind the viewer's routes."""

    def __init__(self, recording, rois: Optional[Path] = None, opener=None):
        """``recording`` names the file (its path is the cache key and the ROI file's default name).
        ``opener``: how to open it, when it is not a `.mesc` — a zero-argument callable returning an
        object with MescFile's reading interface (a MescFile subclass over another HDF5 layout)."""
        recording = Path(recording)
        rois = Path(rois) if rois else _viewer.default_rois_path(recording)
        # a subclass per Engine: the viewer keeps the recording, ROI file, cache and locks on the class
        self._cls = type("_EngineHandler", (_Captured,), {
            "mesc_path": recording, "rois_path": rois,
            "_opener": staticmethod(opener) if opener is not None else None,
            "_lock": threading.Lock(), "_store_lock": threading.Lock(), "_cache": _viewer._BoundedCache()})
        self.recording, self.rois = recording, rois

    def handle(self, method: str, path: str, body: bytes = b"",
               headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], bytes]:
        """``path`` as the viewer sees it (``/api/frame/MSession_0/MUnit_2/0/100?n=5``), any mount prefix removed."""
        h = self._cls(method.upper(), path, body, headers)
        fn = {"GET": h.do_GET, "PUT": h.do_PUT, "POST": h.do_POST}.get(method.upper())
        if fn is None:
            return 405, {"Content-Type": "application/json"}, b'{"error": "method not allowed"}'
        fn()
        return h._status, h._out_headers, h.wfile.getvalue()
