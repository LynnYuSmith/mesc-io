"use strict";
/* The page's fast paths draw what the slow ones drew -- in a real Chrome, over CDP, no puppeteer.
   NOT collected by pytest: needs Chrome and two running viewers.

     python tools/make_synthetic.py && python tools/make_synthetic.py --stack
     mesc-io view synthetic_view.mesc --port 8031 --no-browser &
     mesc-io view synthetic_stack.mesc --port 8032 --no-browser &
     node tests/view_fastpaths_real_chrome.js http://127.0.0.1:8031/ http://127.0.0.1:8032/

   Held, against the code they replaced (copied below as it stood in 0.3.11):
   * composite(): one channel in grey is the PNG itself, any palette and the two-channel overlay
     go through packed tables -- the pixels on screen equal the old per-pixel loop's, byte for byte;
   * the XYZ panes: the same bytes as the old forEach loop, one channel and two, each switch;
   * the blob cut, run in steps that yield to the page: the same bytes as the cut in one go;
   * the traces: past one frame per pixel the line goes through each column's first, lowest,
     highest and last frame -- each column spans what the line through every frame spans (to a
     pixel, measured with round joins: with the default miter joins the old dense line grew
     spikes past its true peaks, which the new one has fewer of), the one-frame spike reaches
     the same row; at one frame per pixel or fewer, the old line exactly;
     the frame cursor moves without the traces being redrawn, and a selection still redraws them;
   * scrubbing: 30 slider steps while a frame is on its way make one or two requests, not 30, and the
     last one shown is where the slider stopped. */
const { spawn } = require("node:child_process"); const http = require("node:http");
const REC = process.argv[2], STK = process.argv[3];
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9338;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const getJSON = (u) => new Promise((res, rej) => http.get(u, r => { let b = ""; r.on("data", d => b += d); r.on("end", () => res(JSON.parse(b))); }).on("error", rej));

// ---- the code as it was (0.3.11), evaluated in the page beside the new ----
const OLD = String.raw`
window.__oldComposite = function (images, chans) {
  const w = unit.width, h = unit.height;
  const out = document.createElement("canvas"); out.width = w; out.height = h;
  const tmp = document.createElement("canvas"); tmp.width = w; tmp.height = h;
  const tg = tmp.getContext("2d", { willReadFrequently: true });
  const acc = new Uint16Array(w * h * 3);
  images.forEach((im, j) => {
    tg.clearRect(0, 0, w, h); tg.drawImage(im, 0, 0, w, h);
    const px = tg.getImageData(0, 0, w, h).data, L = lutOf(paletteFor(chans[j]));
    for (let i = 0, p = 0; i < px.length; i += 4, p += 3) { const c = L[px[i]]; acc[p] += c[0]; acc[p + 1] += c[1]; acc[p + 2] += c[2]; }
  });
  const og = out.getContext("2d"), od = og.createImageData(w, h);
  for (let i = 0, p = 0; i < od.data.length; i += 4, p += 3) {
    od.data[i] = Math.min(255, acc[p]); od.data[i + 1] = Math.min(255, acc[p + 1]); od.data[i + 2] = Math.min(255, acc[p + 2]); od.data[i + 3] = 255;
  }
  og.putImageData(od, 0, 0);
  return out;
};
window.__oldOrtho = function (axis) {
  const v = V.vol, pl = orthoPlane(axis), im = new ImageData(pl.w, pl.h);
  if (!volMeta.ov) for (let i = 0; i < pl.px.length; i++) { const q = pl.px[i]; im.data[4 * i] = im.data[4 * i + 1] = im.data[4 * i + 2] = q; im.data[4 * i + 3] = 255; }
  else {
    const cols = volColours(), shown = [0, 1].filter(j => v.chOn[j]), pls = shown.map(j => orthoPlane(axis, j).px);
    for (let i = 0; i < pl.px.length; i++) {
      for (let ci = 0; ci < 3; ci++) { let s = 0; shown.forEach((j, n) => { s += cols[j][ci] * pls[n][i]; }); im.data[4 * i + ci] = Math.min(255, s); }
      im.data[4 * i + 3] = 255; }
  }
  return im.data;
};
window.__oldCut = function (j) {
  const src = volBytes[j];
  const [D, Hy, Wx] = volMeta.shape, [vz, vy, vx] = volMeta.vox, lim = Math.floor(V.vol.ceilSet * 255);
  let m = new Uint8Array(src.length);
  for (let i = 0; i < m.length; i++) m[i] = src[i] > lim ? 1 : 0;
  const grow = (src, n, stride, count, step, r) => {
    const out = new Uint8Array(src.length);
    for (let line = 0; line < count; line++) {
      const base = Math.floor(line / step) * step * n + (line % step);
      let run = 0;
      for (let k = 0; k <= Math.min(r, n - 1); k++) run += src[base + k * stride];
      for (let k = 0; k < n; k++) {
        if (run > 0) out[base + k * stride] = 1;
        const add = k + r + 1, drop = k - r;
        if (add < n) run += src[base + add * stride];
        if (drop >= 0) run -= src[base + drop * stride];
      }
    }
    return out;
  };
  const rx = Math.max(1, Math.round(BLOB_RIM_UM / vx)), ry = Math.max(1, Math.round(BLOB_RIM_UM / vy));
  const rz = Math.max(1, Math.round(BLOB_RIM_UM / vz));
  m = grow(m, Wx, 1, D * Hy, 1, rx); m = grow(m, Hy, Wx, D * Wx, Wx, ry); m = grow(m, D, Wx * Hy, Wx * Hy, Wx * Hy, rz);
  const out = new Uint8Array(src.length);
  for (let i = 0; i < out.length; i++) out[i] = m[i] ? 0 : src[i];
  return out;
};
window.__same = (a, b) => { if (a.length !== b.length) return "length " + a.length + " vs " + b.length;
  let n = 0, first = -1; for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) { n++; if (first < 0) first = i; }
  return n ? n + " bytes differ, first at " + first : ""; };
window.__pixels = (src, w, h) => { const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d");
  g.imageSmoothingEnabled = false; g.drawImage(src, 0, 0, w, h); return g.getImageData(0, 0, w, h).data; };
`;

(async () => {
  const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=" + PORT, "--no-first-run", "--user-data-dir=/tmp/view_fastpaths_profile", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
  process.on("exit", () => { try { chrome.kill(); } catch (_) {} });
  process.on("SIGINT", () => process.exit(130));
  let targets; for (let i = 0; i < 30; i++) { try { targets = await getJSON(`http://127.0.0.1:${PORT}/json`); break; } catch { await sleep(300); } }
  const ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let id = 0; const pending = new Map(); const errors = [];
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    else if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text); };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text + " " + (r.result.exceptionDetails.exception || {}).description); return r.result.result.value; };
  const fail = (m) => { console.error("  FAIL: " + m); chrome.kill(); process.exit(1); };
  await send("Page.enable"); await send("Runtime.enable");

  /* ---------------- the stack: composite, XYZ, cut ---------------- */
  await send("Page.navigate", { url: STK }); await sleep(1800);
  await ev(OLD);
  await ev(`pick(0); V.proj=""; V.frame=20; V.avg=1; V.overlay=false; V.vol.on=false; V.vol.ortho=false; volShow(); draw(); 'ok'`); await sleep(800);
  // composite: the same two decoded images through the old loop and the new tables
  const comp = JSON.parse(await ev(`(async () => {
    const ld = u => new Promise((ok, bad) => { const im = new Image(); im.onload = () => ok(im); im.onerror = bad; im.src = u; });
    const a = await ld(frameUrl(0)), b = await ld(frameUrl(1)), w = unit.width, h = unit.height, out = {};
    const cases = [["grey", [a], [0], null], ["#00ff00", [a], [0], null], ["batlow", [a], [0], null], ["magenta", [b], [1], null],
                   ["overlay file", [a, b], [0, 1], true], ["overlay batlow+red", [a, b], [0, 1], ["batlow", "red"]]];
    for (const [name, ims, chans, ov] of cases) {
      V.overlay = !!ov; V.cmapBy = {};
      if (Array.isArray(ov)) { V.cmapBy[unit.path + "|0"] = ov[0]; V.cmapBy[unit.path + "|1"] = ov[1]; }
      else if (!ov) V.cmapBy[unit.path + "|" + chans[0]] = name;
      const nw = composite(ims, chans), od = __oldComposite(ims, chans);
      out[name] = { diff: __same(__pixels(nw, w * 3, h * 3), __pixels(od, w * 3, h * 3)), passthrough: nw instanceof HTMLImageElement };
    }
    V.overlay = false; V.cmapBy = {}; return JSON.stringify(out); })()`));
  console.log("  composite   :", JSON.stringify(comp));
  for (const [k, r] of Object.entries(comp)) if (r.diff) fail(`composite ${k}: ${r.diff}`);
  if (!comp.grey.passthrough) fail("one grey channel did not use the PNG as it came");
  if (comp["#00ff00"].passthrough) fail("a coloured palette was passed through as grey");

  // XYZ: every pane, one channel and two, each switch, against the old loop
  await ev(`V.vol.ortho=true; V.vol.on=false; V.vol.oMax=false; V.vol.cx=40; V.vol.cy=70; V.frame=21; volShow(); 'ok'`);
  for (let i = 0; i < 40 && !(await ev("!!volMeta && !!volData")); i++) await sleep(250);
  const ortho = JSON.parse(await ev(`(() => { const out = {};
    const run = tag => { orthoDraw(); for (const ax of ["xy", "yz", "xz"]) { const d = __same(orthoPicture(ax).getContext("2d").getImageData(0, 0, orthoPlane(ax).w, orthoPlane(ax).h).data, __oldOrtho(ax)); if (d) out[tag + " " + ax] = d; } };
    run(volMeta.ov ? "two" : "one");
    V.overlay = true; showWin(); volShow(); return JSON.stringify(out); })()`));
  for (let i = 0; i < 40 && !(await ev("!!volMeta && volMeta.ov")); i++) await sleep(250);
  Object.assign(ortho, JSON.parse(await ev(`(() => { const out = {};
    const run = tag => { orthoDraw(); for (const ax of ["xy", "yz", "xz"]) { const d = __same(orthoPicture(ax).getContext("2d").getImageData(0, 0, orthoPlane(ax).w, orthoPlane(ax).h).data, __oldOrtho(ax)); if (d) out[tag + " " + ax] = d; } };
    run("two"); V.vol.chOn = [false, true]; run("ch1 only"); V.vol.chOn = [true, false]; run("ch0 only"); V.vol.chOn = [false, false]; run("none");
    V.vol.chOn = [true, true]; V.vol.oMax = true; run("two max"); V.vol.oMax = false;
    V.cmapBy[unit.path + "|0"] = "batlow"; run("batlow"); V.cmapBy = {};
    out.ov = volMeta.ov; return JSON.stringify(out); })()`)));
  const odiff = Object.entries(ortho).filter(([k]) => k !== "ov");
  console.log("  XYZ panes   :", odiff.length ? JSON.stringify(odiff) : "equal to the old loop (one channel, two, each switch, max, a palette)");
  if (!ortho.ov) fail("the overlay did not reach the XYZ views");
  if (odiff.length) fail("an XYZ pane differs from the old loop");
  // a crosshair step along x redraws YZ only
  const panes = JSON.parse(await ev(`(() => { orthoDraw(); const before = { xy: oPane.xy.off, yz: oPane.yz.off, xz: oPane.xz.off };
    V.vol.cx += 3; orthoDraw(); return JSON.stringify({ xy: oPane.xy.off === before.xy, yz: oPane.yz.off === before.yz, xz: oPane.xz.off === before.xz }); })()`));
  console.log("  cx step     :", JSON.stringify(panes), "(true = kept)");
  if (!panes.xy || panes.yz || !panes.xz) fail("a step along x should rebuild YZ alone");

  // the cut: in steps, in the background, the same bytes as in one go
  const cut = JSON.parse(await ev(`(async () => {
    V.vol.cut = true; V.vol.ceil = V.vol.ceilSet = 0.5; volCut = {};
    const old = [0, 1].map(j => __oldCut(j));
    volCutRun = ""; volCutAsync();
    for (let i = 0; i < 200 && !volCutReady(); i++) await new Promise(r => setTimeout(r, 25));
    const ready = volCutReady(), d = [0, 1].map(j => volCut[j] ? __same(volCut[j].out, old[j]) : "missing");
    const sync = (volCut = {}, [0, 1].map(j => __same(volCutData(j), old[j])));
    let changed = 0; for (let i = 0; i < old[0].length; i++) if (old[0][i] !== volBytes[0][i]) changed++;
    V.vol.cut = false; V.vol.ceil = V.vol.ceilSet = 1; volCut = {};
    return JSON.stringify({ ready, async: d, sync, changed }); })()`));
  console.log("  cut         :", JSON.stringify(cut));
  if (!cut.ready || cut.async.some(Boolean) || cut.sync.some(Boolean)) fail("the stepped cut differs from the cut in one go");
  if (!(cut.changed > 0)) fail("the cut test cut nothing: it cannot tell anything apart");

  /* ---------------- the recording: traces and scrubbing ---------------- */
  await send("Page.navigate", { url: REC }); await sleep(1800);
  await ev(OLD);
  await ev(`pick(0); V.proj=""; V.frame=100; V.avg=1; V.overlay=false; V.traceMode="stack"; V.traceZoom=null; V.valueZoom=null; V.yFixed=null; draw(); 'ok'`); await sleep(500);
  await ev(`(()=>{ ROIS.length=0; for (let i = 0; i < 6; i++) ROIS.push(makeSpot(20 + i * 15, 64, 3));
    const N = unit.frames, mk = k => Array.from({ length: N }, (_, f) => 1000 + 200 * Math.sin(f / (20 + k)) + ((f * 7919 + k * 104729) % 97) - (f === 700 + k ? -900 : 0));
    TR = { unit: unit.path, channel: 0, names: ROIS.map(r => r.name), traces: ROIS.map((_, k) => mk(k)), areas_px: ROIS.map(() => 29) }; TR.dff = TR.traces;
    renderRois(); plotTraces(); return 'ok'; })()`);
  // the M4 line against the line through every frame, both drawn the same way into spare canvases
  const m4 = JSON.parse(await ev(`(() => {
    const W = 260, H = 64, dpr = devicePixelRatio || 1, mk = () => { const c = document.createElement("canvas"); c.width = W * dpr; c.height = H * dpr; const g = c.getContext("2d"); g.scale(dpr, dpr); return [c, g]; };
    const res = {};
    for (const [t0, t1] of [[0, unit.frames - 1], [500, 900], [650, 800]]) {
      const X = f => TL + (f - t0) / Math.max(1, t1 - t0) * (W - TL - TR_), v = TR.traces[0], seg = v.slice(t0, t1 + 1), lo = Math.min(...seg), hi = Math.max(...seg), Y = x => 4 + 56 - (x - lo) / ((hi - lo) || 1) * 56;   // min..max: the one-frame spike is the top, and must reach it
      const [ca, ga] = mk(), [cb, gb] = mk();
      ga.lineWidth = gb.lineWidth = 1.3; ga.strokeStyle = gb.strokeStyle = "#fff";
      ga.lineJoin = gb.lineJoin = "round";
      ga.beginPath(); traceLine(ga, v, t0, t1, X, Y); ga.stroke();
      gb.beginPath(); for (let f = t0; f <= t1; f++) f === t0 ? gb.moveTo(X(f), Y(v[f])) : gb.lineTo(X(f), Y(v[f])); gb.stroke();
      const a = ga.getImageData(0, 0, ca.width, ca.height).data, b = gb.getImageData(0, 0, cb.width, cb.height).data;
      // what the eye reads at this density is each column's extent: its top and bottom lit pixel
      let lit = 0, off = 0, topA = H * dpr, topB = H * dpr, ext = 0;
      for (let i = 3; i < a.length; i += 4) { if (b[i] > 60) lit++; if (Math.abs(a[i] - b[i]) > 8) off++;
        const row = Math.floor((i >> 2) / ca.width); if (a[i] > 128) topA = Math.min(topA, row); if (b[i] > 128) topB = Math.min(topB, row); }
      for (let x = Math.ceil(TL * dpr) + 2; x < Math.floor((W - TR_) * dpr) - 2; x++) {
        const span = d => { let t = -1, u = -1; for (let y = 0; y < ca.height; y++) if (d[(y * ca.width + x) * 4 + 3] > 128) { if (t < 0) t = y; u = y; } return [t, u]; };
        const [ta, ua] = span(a), [tb, ub] = span(b); ext = Math.max(ext, Math.abs(ta - tb), Math.abs(ua - ub)); }
      res[t0 + "-" + t1] = { frames_per_px: +((t1 - t0) / ((W - TL - TR_) * dpr)).toFixed(2), lit, differ_px: off, column_extent_off_px: ext, spike_top: [topA, topB] };
    }
    return JSON.stringify(res); })()`));
  console.log("  M4 vs every frame:", JSON.stringify(m4));
  for (const [k, r] of Object.entries(m4)) {
    if (r.frames_per_px <= 1 && r.differ_px) fail(`at ≤1 frame per pixel the line must be the old one exactly (${k}: ${r.differ_px} px differ)`);
    if (r.column_extent_off_px > 1) fail(`a column's extent moved by ${r.column_extent_off_px} px (${k})`);
    if (Math.abs(r.spike_top[0] - r.spike_top[1]) > 1) fail(`the spike's top moved (${k}: ${r.spike_top})`);
  }
  // the cursor moves, the traces are not redrawn; a selection redraws them
  const cur = JSON.parse(await ev(`(() => { let n = 0; const g = $("trace").getContext("2d"), o = g.clearRect; g.clearRect = function () { n++; return o.apply(this, arguments); };
    plotTraces(); const k0 = n, x0 = $("traceCursor").style.transform;
    const s = $("frame"); s.value = 300; s.oninput(); const x1 = $("traceCursor").style.transform, k1 = n;
    V.sel = 2; renderRois(); plotTraces(); const k2 = n; g.clearRect = o;
    V.proj = "mean"; plotTraces(); const hid = $("traceCursor").style.display; V.proj = ""; plotTraces();
    return JSON.stringify({ x0, x1, redraws_on_step: k1 - k0, redraws_on_select: k2 - k1, hidden_on_mean: hid === "none", shown: $("traceCursor").style.display }); })()`));
  console.log("  cursor      :", JSON.stringify(cur));
  if (cur.x0 === cur.x1) fail("the frame cursor did not move with the slider");
  if (cur.redraws_on_step !== 0) fail("a frame step redrew the traces");
  if (cur.redraws_on_select < 1) fail("a selection did not redraw the traces");
  if (!cur.hidden_on_mean || cur.shown !== "block") fail("the cursor should hide on a projection and come back");
  // scrubbing: one frame in flight; the last one shown is where the slider stopped
  const scrub = JSON.parse(await ev(`(async () => { let n = 0; const im = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
    Object.defineProperty(HTMLImageElement.prototype, "src", { set(v) { if (String(v).includes("/api/frame/")) n++; im.set.call(this, v); }, get() { return im.get.call(this); }, configurable: true });
    // faster than the synthetic file's frames come back (a real file's take 50-120 ms): no pause between steps
    const s = $("frame"); for (let i = 0; i < 30; i++) { s.value = 400 + i * 10; s.oninput(); }
    for (let i = 0; i < 100 && (frameInFlight || frameWanted); i++) await new Promise(r => setTimeout(r, 30));
    Object.defineProperty(HTMLImageElement.prototype, "src", im);
    return JSON.stringify({ inputs: 30, frame_requests: n, last: imgUrl.split("?")[0], want: "/" + 690 }); })()`));
  console.log("  scrub       :", JSON.stringify(scrub));
  if (!scrub.last.endsWith(scrub.want)) fail("the frame shown after scrubbing is not where the slider stopped");
  if (scrub.frame_requests > 3) fail("every slider step still asked for its own frame");

  if (errors.length) fail("console errors: " + errors.join(" | "));
  console.log("\n  fast paths draw what the old ones drew");
  chrome.kill(); process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
