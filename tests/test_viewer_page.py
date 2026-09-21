"""The page's script runs to the end of boot() without throwing — under pytest, on every CI OS.

Until 2026-09-18 nothing under pytest ever fetched the page: a viewer.html that threw on its
first line passed the whole suite green (2026-09-18 review). The real-mouse checks stay
the oracle for behaviour (tests/view_real_chrome.js, a real Chrome, not run by pytest); this
is the cheap hermetic gate for the failure class those cannot reach in CI — a ReferenceError,
a const rebind, a typo in an id, a listener on an element that does not exist.

How: node runs the inline script in a `vm` against a thin DOM stub (every element exists,
every method is a no-op, fetch answers the file description with one unit), then calls what
boot() wires up. Any exception anywhere fails the test. Skipped, visibly, when node is absent.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "src" / "mesc_io" / "viewer.html"
NODE = shutil.which("node")

STUB = r"""
"use strict";
const vm = require("node:vm");
const src = require("node:fs").readFileSync(process.argv[2], "utf8");
const m = src.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error("no inline script"); process.exit(2); }
const ids = [...src.matchAll(/id="([^"]+)"/g)].map(x => x[1]);

const anything = () => new Proxy(function () {}, { get: (t, k) => k === "then" ? undefined : anything(), apply: () => anything(), set: () => true });
function el(tag) {
  const listeners = {}; let cls = "";
  const node = {
    tagName: (tag || "div").toUpperCase(), style: {}, dataset: {}, children: [], value: "", textContent: "",
    placeholder: "", checked: false, disabled: false, hidden: false, scrollTop: 0, scrollHeight: 0,
    clientWidth: 800, clientHeight: 600, width: 800, height: 600, innerHTML: "",
    classList: { add(...c) { c.forEach(x => cls += " " + x); }, remove() {}, toggle() {}, contains: () => false },
    appendChild(c) { this.children.push(c); return c; }, replaceWith() {}, remove() {}, closest: () => null,
    addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); }, removeEventListener() {},
    dispatchEvent(ev) { (listeners[ev.type] || []).forEach(f => f(ev)); return true; },
    setAttribute() {}, getAttribute: () => null, querySelector: () => el(), querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600, x: 0, y: 0 }),
    getContext: () => anything(), focus() {}, blur() {}, select() {}, click() { if (this.onclick) this.onclick({ preventDefault() {}, stopPropagation() {} }); },
    scrollIntoView() {}, includes: () => false,
  };
  Object.defineProperty(node, "className", { get: () => cls.trim(), set: v => { cls = String(v); } });
  return node;
}
const byId = new Map(ids.map(i => [i, el(i === "view" || i === "trace" ? "canvas" : "div")]));
const document = {
  getElementById(id) { if (!byId.has(id)) { console.error("page asked for an id the markup does not have: #" + id); process.exitCode = 3; byId.set(id, el()); } return byId.get(id); },
  createElement: (tag) => el(tag), querySelector: () => el(), querySelectorAll: () => [],
  addEventListener() {}, body: el("body"), documentElement: { style: { setProperty() {} } }, activeElement: null,
  elementFromPoint: () => null,
};
document.body.dataset = {};
const FILE = { file: "synthetic.mesc", path: "/x/synthetic.mesc", findings: [], units: [
  { path: "MSession_0/MUnit_0", name: "MUnit_0", session: "MSession_0", frames: 100, height: 8, width: 8,
    frame_rate_hz: 60.0, duration_s: 1.6, pixel_size_um: 0.5, comment: "c", channels: ["Channel_0"], stage_um: null, stage_rel_um: null }]};
const json = (o) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(o) });
const fetch = (url, opts) => {
  if (url.startsWith("/api/file")) return json(FILE);
  if (url.startsWith("/api/view")) return json({ view: {} });
  if (url.startsWith("/api/rois")) return json({ unit: "MSession_0/MUnit_0", rois: [], units_with_rois: {} });
  return json({});
};
const winListeners = {};
const sandbox = {
  document, fetch, console, window: null, Image: class { set src(v) { this._s = v; if (this.onload) setTimeout(() => this.onload(), 0); } },
  ResizeObserver: class { observe() {} }, requestAnimationFrame: (f) => 0, setTimeout, clearTimeout,
  setInterval: (f) => { f(); f(); return 1; }, clearInterval() {},        // play's tick runs twice, synchronously
  location: { href: "http://127.0.0.1/" }, confirm: () => true, alert() {}, Math, JSON, Date, Object, Array, Number, String, Boolean,
  Float64Array, Map, Set, Promise, Error, TypeError, isFinite, isNaN, parseFloat, parseInt, encodeURIComponent, decodeURIComponent,
  devicePixelRatio: 1, innerWidth: 1400, innerHeight: 900, addEventListener(t, f) { (winListeners[t] = winListeners[t] || []).push(f); }, Event: class { constructor(t) { this.type = t; } },
};
sandbox.window = sandbox; sandbox.globalThis = sandbox;
process.on("unhandledRejection", (e) => { console.error("unhandled: " + (e && e.stack || e)); process.exit(4); });
try {
  vm.runInContext(m[1], vm.createContext(sandbox), { filename: "viewer.html(inline)" });
} catch (e) { console.error("threw at load: " + (e && e.stack || e)); process.exit(5); }
// let boot()'s fetches and the deferred image load resolve, then exercise the wiring a click would
setTimeout(() => {
  try {
    for (const id of ["meanBtn", "modeOverlay", "modeStack", "gridBtn", "sigDff", "sigRaw", "toolRect", "toolSpot", "traceReset", "yAuto", "doTraces", "playBtn", "playBtn", "avgN"]) {
      const b = byId.get(id); if (b && b.onclick) b.onclick({ preventDefault() {}, stopPropagation() {} });
    }
    // the inputs' handlers too: the slider, the AVG field, the y-limits, the dF/F knobs
    for (const id of ["frame", "avgN", "lo", "hi", "yLo", "yHi", "dffQ", "dffWin", "roiFilter", "spotR", "rectW", "rectH"]) {
      const b = byId.get(id); if (!b) continue; b.value = "3";
      if (b.oninput) b.oninput({ target: b }); if (b.onchange) b.onchange({ target: b });
    }
    // and the keys the page listens for on the window
    for (const key of [" ", "ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "Enter", "Escape", "Delete"]) {
      for (const f of (winListeners.keydown || [])) f({ key, target: { tagName: "BODY" }, preventDefault() {}, shiftKey: false });
    }
    // boot() set the file name; pick() wrote the unit into the metadata: both must have run
    const fname = byId.get("fname").textContent, meta = byId.get("metaTable").innerHTML;
    if (fname !== "synthetic.mesc" || !meta.includes("MUnit_0")) { console.error("boot()/pick() did not complete: fname=" + fname + " meta=" + meta.slice(0, 60)); process.exit(7); }
    console.log("page loaded, boot() and pick() completed, every button's handler ran");
    if (process.exitCode) process.exit(process.exitCode);
    process.exit(0);
  } catch (e) { console.error("threw in a handler: " + (e && e.stack || e)); process.exit(6); }
}, 50);
"""


@pytest.mark.skipif(not NODE, reason="node is not on this machine; the page-load gate needs it")
def test_the_page_loads_and_its_handlers_run_without_throwing(tmp_path):
    stub = tmp_path / "load.js"
    stub.write_text(STUB, encoding="utf-8")
    r = subprocess.run([NODE, str(stub), str(PAGE)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"exit {r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "page loaded" in r.stdout


@pytest.mark.skipif(not NODE, reason="node is not on this machine")
def test_the_gate_catches_a_page_that_throws_at_load(tmp_path):
    """The positive control: a page whose script references a name that does not exist must
    turn the gate red, or the gate proves nothing."""
    broken = tmp_path / "broken.html"
    broken.write_text(PAGE.read_text(encoding="utf-8").replace("<script>", "<script>\nthisNameDoesNotExist();\n", 1))
    stub = tmp_path / "load.js"
    stub.write_text(STUB, encoding="utf-8")
    r = subprocess.run([NODE, str(stub), str(broken)], capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "threw at load" in r.stderr


def test_every_id_the_script_asks_for_exists_in_the_markup():
    """Cheaper than node and needs nothing: every `$("id")` in the script has an `id="…"`."""
    src = PAGE.read_text(encoding="utf-8")
    script = re.search(r"<script>([\s\S]*?)</script>", src).group(1)
    markup = src[:src.index("<script>")]
    ids = set(re.findall(r'id="([^"]+)"', markup))
    asked = set(re.findall(r'\$\("([A-Za-z0-9_]+)"\)', script))
    missing = sorted(asked - ids)
    assert not missing, f"the script asks for ids the markup lacks: {missing}"
