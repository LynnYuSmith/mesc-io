"""The engine's browser module api.js: served at /static/, and every viewer URL goes through its base.

Why it matters: a host (the CIP playground) mounts the engine under /mesc. A URL built as a bare
"/api/…" would then hit the HOST's server, not the engine — the page half-works and fails silently."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "src" / "mesc_io"
PAGE = PKG / "viewer.html"
API = PKG / "static" / "api.js"
NODE = shutil.which("node")


def _script(src: str) -> str:
    return re.search(r"<script>([\s\S]*?)</script>", src).group(1)


def _bare(script: str) -> list[str]:
    """Each "/api/" must sit right after `API.base + "` or `${API.base}`; anything else bypasses the base."""
    out = []
    for m in re.finditer(r"/api/", script):
        before = script[max(0, m.start() - 12):m.start()]
        line = script[script.rfind("\n", 0, m.start()) + 1:].split("\n", 1)[0].strip()
        if line.startswith("//") or line.startswith("*"):
            continue
        if not (before.endswith('API.base + "') or before.endswith("${API.base}")):
            out.append(line[:90])
    return out


def test_no_engine_url_bypasses_the_base():
    """Can fail: one bare fetch("/api/x") does it (see the next test)."""
    script = _script(PAGE.read_text(encoding="utf-8"))
    assert script.count("/api/") >= 20                     # the check is looking at the real thing
    assert not _bare(script), f"engine URLs that ignore the base: {_bare(script)}"


def test_the_check_above_can_fail():
    script = _script(PAGE.read_text(encoding="utf-8"))
    assert _bare(script + '\nfetch("/api/oops");\n') == ['fetch("/api/oops");']
    assert _bare(script + "\nconst u = `/api/frame/${x}`;\n")


def test_page_loads_api_before_its_own_script():
    src = PAGE.read_text(encoding="utf-8")
    assert src.index('<script src="static/api.js"></script>') < src.index("<script>")


NODE_CHECK = r"""
const vm = require("node:vm"), fs = require("node:fs");
const out = [];
function load(scriptSrc) {
  const sb = { URL, console, document: scriptSrc === null ? undefined : { currentScript: { src: scriptSrc } } };
  sb.window = sb; vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), vm.createContext(sb)); return sb.MescIO;
}
let M = load("http://127.0.0.1:8040/mesc/static/api.js");
let a = M.createApi();
out.push(a.base, a.url("/api/file"), a.frameUrl("MSession_0/MUnit_0", 0, 5, "n=3"));
M = load("http://127.0.0.1:8031/static/api.js"); a = M.createApi();
out.push(a.base, a.url("/api/file"));
M = load(null); a = M.createApi(); out.push(a.base);
a = M.createApi("/elsewhere/"); out.push(a.url("/api/rois"));
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="node is not on this machine")
def test_base_is_found_from_where_the_script_was_loaded(tmp_path):
    import json
    js = tmp_path / "check.js"
    js.write_text(NODE_CHECK, encoding="utf-8")
    r = subprocess.run([NODE, str(js), str(API)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [
        "/mesc", "/mesc/api/file", "/mesc/api/frame/MSession_0/MUnit_0/0/5?n=3",   # mounted under /mesc
        "", "/api/file",                                                           # standalone viewer
        "",                                                                        # no document: plain
        "/elsewhere/api/rois",                                                     # explicit base wins
    ]


# --- served by the viewer AND by the engine (so a host mounting the engine gets /mesc/static/api.js) ---
from test_engine import _get, standalone  # noqa: E402,F401  (fixture reuse)


def test_viewer_serves_api_js(standalone):
    _, base, _ = standalone
    code, body = _get(base + "/static/api.js")
    assert code == 200 and body == API.read_bytes()


@pytest.mark.parametrize("bad", ["/static/../viewer.py", "/static/nope.js", "/static/API.js", "/static/a/b.js",
                                 "/static/viewer.html"])
def test_static_refuses_anything_but_a_module_of_its_own(standalone, bad):
    _, base, _ = standalone
    code, _ = _get(base + bad)
    assert code == 404


def test_engine_serves_api_js_too(tmp_path):
    from mesc_io.engine import Engine
    from test_engine import _rec
    eng = Engine(_rec(tmp_path / "rec.mesc"), rois=tmp_path / "r.json")
    s, h, b = eng.handle("GET", "/static/api.js")
    assert s == 200 and b == API.read_bytes()
    assert "javascript" in str(h).lower()
