"""image.js: mapping ↔ toImage are inverses (also in MESc's flipped view), and the loader keeps ONE frame in flight."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "src" / "mesc_io"
IMAGE = PKG / "static" / "image.js"
PAGE = PKG / "viewer.html"
NODE = shutil.which("node")

CHECK = r"""
const vm = require("node:vm"), fs = require("node:fs");
const pending = [];
class FakeImage { set src(v) { this._s = v; pending.push(this); } }
const sb = { console, Promise, setTimeout }; sb.window = sb;
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), vm.createContext(sb));
const I = sb.MescIO.image, out = {};
// 1) mapping/toImage round trip, plain and flipped, zoomed and not
const rect = { left: 10, top: 20 };
let worst = 0;
for (const fy of [false, true]) for (const zoom of [{ w: 0 }, { x: 30, y: 40, w: 50, h: 25 }]) {
  const m = I.mapping(800, 600, zoom, 256, 200, fy);
  for (const [x, y] of [[0, 0], [255, 199], [37.5, 120.25]]) {
    const cx = rect.left + m.ox + x * m.k, cy = rect.top + m.sy(y);
    const [bx, by] = I.toImage(cx, cy, rect, m, 200);
    worst = Math.max(worst, Math.abs(bx - x), Math.abs(by - y));
  }
}
out.roundtrip_worst = worst;
// the whole image fits the stage, centred; flipped, row 0 is at the BOTTOM
const m0 = I.mapping(800, 600, { w: 0 }, 256, 200, false), m1 = I.mapping(800, 600, { w: 0 }, 256, 200, true);
out.k = m0.k; out.row0_plain = m0.sy(0); out.row0_flipped = m1.sy(0);
// 2) loader: three quick requests while the first loads → one load, then ONE more for the latest
const L = I.createLoader(() => new FakeImage());
const log = [];
const cb = (tag) => ({ isCurrent: () => true, onLoad: () => log.push("load " + tag), onError: () => log.push("err " + tag), again: () => log.push("again") });
out.r1 = L.request("A", ["a"], cb("A"));
out.r2 = L.request("B", ["b"], cb("B"));
out.r3 = L.request("C", ["c"], cb("C"));
out.r4 = L.request("A", ["a"], cb("A"));          // the shown key again
out.inflight = pending.length; out.busy = L.busy; out.wanted = L.wanted;
pending[0].onload();
setTimeout(() => {
  out.log = log; out.busy_after = L.busy;
  // a frame that lands after the host moved on is dropped
  const L2 = I.createLoader(() => new FakeImage()); let moved = false; const got = [];
  L2.request("X", ["x"], { isCurrent: () => !moved, onLoad: () => got.push("x"), again() {} });
  moved = true; pending[pending.length - 1].onload();
  setTimeout(() => { out.dropped = got.length === 0; console.log(JSON.stringify(out)); }, 0);
}, 0);
"""


@pytest.mark.skipif(not NODE, reason="node is not on this machine")
def test_image_js(tmp_path):
    js = tmp_path / "c.js"
    js.write_text(CHECK, encoding="utf-8")
    r = subprocess.run([NODE, str(js), str(IMAGE)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["roundtrip_worst"] < 1e-9
    assert o["k"] == 3.0 and o["row0_plain"] == 0.0 and o["row0_flipped"] == 600.0
    assert (o["r1"], o["r2"], o["r3"], o["r4"]) == ("loading", "queued", "queued", "same")
    assert o["inflight"] == 1 and o["busy"] and o["wanted"]          # three asks, ONE image requested
    assert o["log"] == ["load A", "again"] and not o["busy_after"]
    assert o["dropped"]


def test_page_loads_image_js_after_api_and_before_its_script():
    src = PAGE.read_text(encoding="utf-8")
    a, i, s = (src.index('<script src="static/api.js">'), src.index('<script src="static/image.js">'),
               src.index("<script>"))
    assert a < i < s


def test_viewer_serves_image_js(standalone):
    from test_engine import _get
    _, base, _ = standalone
    code, body = _get(base + "/static/image.js")
    assert code == 200 and body == IMAGE.read_bytes()


from test_engine import standalone  # noqa: E402,F401
