/* Exploratory interaction testing of the viewer in a real headless Chrome: scripted edge cases
   (switching units mid-load, the ruler across a unit switch, overlay on one channel, PNG before an
   image, traces with no ROIs, play while switching, crossed windows, extreme sizes, splitters to the
   edges, reload) and then a seeded monkey over every button, slider, key and the image. Every
   console error, uncaught exception, unhandled rejection, HTTP >= 400 and broken invariant is
   reported with the step that caused it. NOT collected by pytest; a tool for before a release.
     mesc-io view <file> --port 8031 --no-browser --rois /tmp/x_rois.json &
     node tests/explore_real_chrome.js http://127.0.0.1:8031/ <seed> <monkey steps>
   Scripted edge scenarios first, then a seeded monkey. Every console error, uncaught exception,
   unhandled rejection, HTTP >= 400 and broken invariant is reported with the step that caused it. */
const { spawn } = require("node:child_process"); const http = require("node:http");
const [URL_, SEED = "1", STEPS = "300"] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b = ""; r.on("data", d => b += d); r.on("end", () => res(JSON.parse(b))); }).on("error", rej));
let rnd = (() => { let s = (+SEED * 2654435761) >>> 0 || 1; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; })();
const pick = a => a[Math.floor(rnd() * a.length)];
(async () => {
  const port = 9400 + (+SEED % 50);
  const ch = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", ["--headless=new", `--remote-debugging-port=${port}`,
    "--no-first-run", `--user-data-dir=/tmp/view_explore_${SEED}`, "--window-size=1440,900", "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "about:blank"], { stdio: "ignore" });
  process.on("exit", () => { try { ch.kill(); } catch (_) {} });
  let t; for (let i = 0; i < 40; i++) { try { t = await getJSON(`http://127.0.0.1:${port}/json`); break; } catch { await sleep(300); } }
  const ws = new WebSocket(t.find(x => x.type === "page").webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let id = 0; const pend = new Map(); const issues = []; let step = "boot";
  const note = (kind, msg) => { const k = kind + "|" + msg.slice(0, 160); if (!issues.some(x => x.k === k)) issues.push({ k, kind, msg: msg.slice(0, 400), step }); };
  ws.onmessage = m => { const d = JSON.parse(m.data);
    if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); return; }
    if (d.method === "Runtime.exceptionThrown") note("exception", d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
    if (d.method === "Runtime.consoleAPICalled" && (d.params.type === "error" || d.params.type === "warning"))
      note("console." + d.params.type, d.params.args.map(a => a.value ?? a.description ?? "").join(" "));
    if (d.method === "Network.responseReceived" && d.params.response.status >= 400)
      note("http " + d.params.response.status, d.params.response.url.replace(/^https?:\/\/[^/]+/, ""));
    if (d.method === "Network.loadingFailed" && !d.params.canceled) note("net failed", d.params.errorText + " " + (d.params.requestId || ""));
  };
  const send = (m, p = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
  const ev = async e => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true });
    if (r.result.exceptionDetails) { note("eval threw", (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text) + " ← " + e.slice(0, 80)); return undefined; }
    return r.result.result.value; };
  const mouse = (type, x, y, extra = {}) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1, ...extra });
  const click = async (x, y, n = 1) => { await mouse("mouseMoved", x, y); for (let c = 1; c <= n; c++) { await mouse("mousePressed", x, y, { clickCount: c }); await mouse("mouseReleased", x, y, { clickCount: c }); } };
  const key = async k => { await send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code: k }); await send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code: k }); };
  const box = async sel => ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)}); if(e&&e.scrollIntoView&&e.closest('#units,#toolsCol')) e.scrollIntoView({block:'nearest'}); if(!e||e.offsetParent===null&&getComputedStyle(e).position!=='fixed') return null; const r=e.getBoundingClientRect(); return r.width&&r.height?[r.left+r.width/2,r.top+r.height/2,r.width,r.height]:null})()`);
  const clickEl = async sel => { const b = await box(sel); if (b) await click(b[0], b[1]); return !!b; };
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
  await ev("window.addEventListener('unhandledrejection', e => console.error('UNHANDLED REJECTION', e.reason && (e.reason.stack || e.reason)))");
  await send("Page.addScriptToEvaluateOnNewDocument", { source: "window.addEventListener('unhandledrejection', e => console.error('UNHANDLED REJECTION', e.reason && (e.reason.stack||e.reason)))" });
  await send("Page.navigate", { url: URL_ }); await sleep(2500);
  // never actually download: export functions hand their canvas to a probe
  await ev("savePng=(c,n)=>{window.__png=(window.__png||0)+1; if(!c.width||!c.height) console.error('PNG with an empty canvas', n);}; 'ok'");
  let lastFrameReq = Date.now();
  const invariants = async () => {
    const r = await ev(`(()=>{const p=[]; if(!unit) return ['no unit'];
      if(!(V.frame>=0 && V.frame<unit.frames)) p.push('V.frame '+V.frame+' outside 0..'+(unit.frames-1));
      if(V.ch>=unit.channels.length) p.push('V.ch '+V.ch+' >= channels '+unit.channels.length);
      if(V.zoom && (V.zoom.w<0||V.zoom.h<0||V.zoom.x<0||V.zoom.y<0||V.zoom.x+V.zoom.w>unit.width+1e-6||V.zoom.y+V.zoom.h>unit.height+1e-6)) p.push('zoom outside image '+JSON.stringify(V.zoom));
      if(typeof ruler!=='undefined' && ruler.length>2) p.push('ruler has '+ruler.length+' points');
      for(const r of ROIS){ for(const [x,y] of r.points) if(!(isFinite(x)&&isFinite(y))) {p.push('ROI '+r.name+' non-finite point'); break;} }
      if(V.sel>=ROIS.length) p.push('V.sel '+V.sel+' >= ROIs '+ROIS.length);
      for(const k of ['lo','hi','avg']) if(!isFinite(V[k])) p.push('V.'+k+' = '+V[k]);
      if(V.lo>=V.hi) p.push('window lo >= hi '+V.lo+' '+V.hi);
      const vb=document.getElementById('volBtn'); if(!unit.z_step_um && V.vol && V.vol.on) p.push('3D on for a time series');
      if(V.overlay && unit.channels.length<2 && document.getElementById('ovBtn').classList.contains('on')) p.push('overlay on with one channel');
      const c=document.getElementById('view'); if(!V.vol.on && !V.vol.ortho && (!c.width||!c.height)) p.push('view canvas 0-sized');
      if(TR && TR.unit && TR.unit!==unit.path && document.getElementById('trace').style.display!=='none' && TR.names && TR.names.length) p.push('traces of '+TR.unit+' shown on '+unit.path);
      return p; })()`);
    (r || []).forEach(x => note("invariant", x));
    const stuck = await ev("frameInFlight"); if (stuck) { if (Date.now() - lastFrameReq > 6000) note("invariant", "frameInFlight stuck true for >6 s"); } else lastFrameReq = Date.now();
  };
  const nUnits = await ev("FILE.units.length");
  const units = await ev("FILE.units.map(u=>({z:!!u.z_step_um,ch:u.channels.length,f:u.frames,w:u.width}))");
  console.log("units:", JSON.stringify(units));
  const S = async (name, fn) => { step = name; try { await fn(); } catch (e) { note("driver", String(e)); } await sleep(350); await invariants(); };
  const stage = async () => box("#stage"); const at = async (fx, fy) => { const b = await stage(); return [b[0] - b[2] / 2 + fx * b[2], b[1] - b[3] / 2 + fy * b[3]]; };
  const unitRow = i => `#units .u:nth-child(${i + 1})`;
  const ts = units.findIndex(u => !u.z), zs = units.findIndex(u => u.z), one = units.findIndex(u => u.ch === 1);

  // ---------------- scripted edge scenarios ----------------
  await S("switch unit while its first frame is loading", async () => { for (let i = 0; i < Math.min(nUnits, 6); i++) { await clickEl(unitRow(i % nUnits)); await sleep(20); } await sleep(1500); });
  await S("ruler, then switch unit, then come back", async () => { await clickEl("#toolRuler"); let [x, y] = await at(.3, .3); await click(x, y); [x, y] = await at(.6, .7); await click(x, y);
    const before = await ev("[unit.path, ruler.length, V.vol.on, V.vol.ortho]");
    const nx = (await ev("FILE.units.indexOf(unit)") + 1) % nUnits, rb = await box(unitRow(nx));
    const hit = rb && await ev(`(()=>{const e=document.elementFromPoint(${rb[0]},${rb[1]}); return e.tagName+'#'+e.id+'.'+e.className})()`);
    await clickEl(unitRow(nx)); await sleep(500); const after = await ev("[unit.path, ruler.length]");
    if (after[1]) note("finding", "ruler survived a unit switch: before " + JSON.stringify(before) + " row " + nx + " hit " + hit + " after " + JSON.stringify(after));
    await clickEl(unitRow(0)); await sleep(400); });
  await S("ruler: one point, then Esc, then a click on an ROI", async () => { await clickEl("#toolRuler"); let [x, y] = await at(.5, .5); await click(x, y); await key("Escape"); await click(x, y); await key("Escape"); });
  await S("ruler + flip + zoom + PNG", async () => { await clickEl("#toolRuler"); let [x, y] = await at(.2, .2); await click(x, y); [x, y] = await at(.8, .4); await click(x, y);
    await clickEl("#flipBtn"); await send("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: 0, deltaY: -300 }); await sleep(300); await ev("exportImagePng()"); await clickEl("#flipBtn"); await key("Escape"); });
  await S("PNG before any image has loaded", async () => { await ev("imgEl=null; exportImagePng()"); await ev("draw()"); await sleep(600); });
  await S("traces PNG with no traces", async () => { await ev("TR=null; exportTracePng()"); });
  await S("traces with no ROIs", async () => { await ev("ROIS.length=0; renderRois(); paint()"); await clickEl("#doTraces"); await sleep(1500); });
  if (one >= 0) await S("overlay on a one-channel unit", async () => { await clickEl(unitRow(one)); await sleep(400); await clickEl("#ovBtn"); await sleep(400); });
  if (ts >= 0) await S("3D/XYZ buttons on a time series", async () => { await clickEl(unitRow(ts)); await sleep(500);
    const v = await ev("[document.getElementById('volBtn').hidden, document.getElementById('orthoBtn').hidden]"); if (v && (!v[0] || !v[1])) note("finding", "3D/XYZ offered for a time series: " + JSON.stringify(v));
    await ev("V.vol.on=true; volShow(); volDraw()"); await sleep(600); await ev("V.vol.on=false; volShow()"); });
  if (ts >= 0) await S("play, then mean, max, overlay, unit switch while playing", async () => { await clickEl(unitRow(ts)); await sleep(400); await clickEl("#playBtn"); await sleep(600);
    await clickEl("#meanBtn"); await sleep(200); await clickEl("#maxBtn"); await sleep(200); await clickEl("#ovBtn"); await sleep(300); await clickEl(unitRow((ts + 1) % nUnits)); await sleep(600);
    const p = await ev("!!playing"); if (p) note("finding", "still playing after a unit switch"); if (await ev("!!playing")) await clickEl("#playBtn"); });
  if (ts >= 0) await S("ROIs, traces requested, ROI deleted before they land", async () => { await clickEl(unitRow(ts)); await sleep(400); await clickEl("#toolSpot");
    for (const [fx, fy] of [[.3, .3], [.5, .5], [.7, .6]]) { const [x, y] = await at(fx, fy); await click(x, y); await sleep(300); }
    await clickEl("#doTraces"); await sleep(30); await ev("V.sel=0"); await key("Delete"); await sleep(2500);
    const r = await ev("TR ? [TR.names.length, ROIS.length] : null"); if (r && r[0] !== r[1]) note("finding", "traces list " + r[0] + " ROIs while " + r[1] + " exist (shown stale?)"); });
  await S("avg extremes typed", async () => { for (const v of ["0", "-5", "1e9", "abc", "64", "1"]) { await ev(`(()=>{const a=document.getElementById('avgN'); a.value=${JSON.stringify(v)}; a.dispatchEvent(new Event('change')); return V.avg})()`); await sleep(250); } });
  await S("window percentiles crossed (lo > hi)", async () => { await ev("(()=>{const l=document.getElementById('lo'),h=document.getElementById('hi'); l.value=99; l.dispatchEvent(new Event('input')); h.value=1; h.dispatchEvent(new Event('input')); return [V.lo,V.hi]})()"); await sleep(500); });
  await S("fixed window with min > max", async () => { await clickEl("#winFixed"); await ev("(()=>{const a=document.getElementById('vmin'),b=document.getElementById('vmax'); a.value=500; b.value=100; a.dispatchEvent(new Event('change')); b.dispatchEvent(new Event('change'))})()"); await sleep(500); await clickEl("#winPct"); });
  await S("rect size zero / huge", async () => { await clickEl("#toolRect"); await ev("(()=>{const w=document.getElementById('rectW'),h=document.getElementById('rectH'); w.value=0; h.value=99999; w.dispatchEvent(new Event('change')); h.dispatchEvent(new Event('change'))})()"); const [x, y] = await at(.95, .95); await click(x, y); await sleep(400); });
  await S("polygon with 2 points then double-click", async () => { await clickEl("#toolPoly"); let [x, y] = await at(.4, .4); await click(x, y); [x, y] = await at(.45, .45); await click(x, y, 2); await sleep(400); await key("Escape"); });
  if (zs >= 0) await S("3D on a stack, switch to a time series while it loads", async () => { await clickEl(unitRow(zs)); await sleep(300); await clickEl("#volBtn"); await sleep(100); if (ts >= 0) await clickEl(unitRow(ts)); await sleep(1500);
    const on = await ev("V.vol.on && !unit.z_step_um"); if (on) note("finding", "3D still on after switching to a time series"); });
  if (zs >= 0) await S("3D PNG, XYZ, back", async () => { await clickEl(unitRow(zs)); await sleep(400); if (!(await ev("V.vol.on"))) await clickEl("#volBtn"); await sleep(1500); await ev("exportVolPng()"); await clickEl("#orthoBtn"); await sleep(800); await clickEl("#orthoBtn"); await sleep(300); });
  await S("splitters dragged to extremes", async () => { for (const id of ["#splitter", "#toolsSplit", "#metaSplit"]) { const b = await box(id); if (!b) continue;
    await mouse("mouseMoved", b[0], b[1]); await mouse("mousePressed", b[0], b[1]); await mouse("mouseMoved", b[0] + 2000, b[1] + 2000, { buttons: 1 }); await mouse("mouseMoved", b[0] - 4000, b[1] - 4000, { buttons: 1 }); await mouse("mouseReleased", b[0] - 4000, b[1] - 4000); } await sleep(300); });
  await S("arrow keys at both ends of the recording", async () => { await ev("(()=>{const f=document.getElementById('frame'); f.value=0; f.dispatchEvent(new Event('input'))})()"); await key("ArrowLeft"); await key("ArrowLeft"); await ev("(()=>{const f=document.getElementById('frame'); f.value=f.max; f.dispatchEvent(new Event('input'))})()"); await key("ArrowRight"); await key("ArrowRight"); await key("ArrowUp"); await key("ArrowDown"); });
  await S("window resized small and back", async () => { await send("Emulation.setDeviceMetricsOverride", { width: 420, height: 380, deviceScaleFactor: 1, mobile: false }); await sleep(600); await send("Emulation.clearDeviceMetricsOverride"); await sleep(600); });
  await S("reload restores the view", async () => { const before = await ev("JSON.stringify({u:unit.path,f:V.frame,ch:V.ch})"); await sleep(800); await send("Page.reload"); await sleep(3000);
    await ev("savePng=(c,n)=>{window.__png=(window.__png||0)+1; if(!c.width||!c.height) console.error('PNG with an empty canvas', n);}; 'ok'");
    const after = await ev("JSON.stringify({u:unit.path,f:V.frame,ch:V.ch})"); if (before !== after) note("finding", "view not restored on reload: " + before + " → " + after); });

  // ---------------- the monkey ----------------
  const targets = ["#playBtn", "#meanBtn", "#maxBtn", "#volBtn", "#orthoBtn", "#flipBtn", "#ovBtn", "#pngBtn", "#toolSpot", "#toolRect", "#toolPoly", "#toolRuler",
    "#winFixed", "#winPct", "#winFile", "#sigRaw", "#sigDff", "#modeStack", "#modeOverlay", "#gridBtn", "#yAuto", "#traceReset", "#doTraces", "#addRoi", "#delRoi",
    "#volMip", "#volGlass", "#volDepth", "#volPoint", "#volMeasure", "#volBox", "#volBoxFull", "#volSlab", "#volCut", "#volAuto", "#volReset", "#volAxY", "#volAxX", "#volDeep", "#oMax", "#oCross", "#dlTracePng"];
  const ranges = ["#frame", "#lo", "#hi", "#volThr", "#volCeil", "#volDen", "#volGain", "#volZ"];
  for (let s = 0; s < +STEPS; s++) {
    const r = rnd(); let what;
    if (r < 0.32) { const id = pick(targets); what = "click " + id; step = "monkey " + s + ": " + what; await clickEl(id); }
    else if (r < 0.42) { const i = Math.floor(rnd() * nUnits); what = "unit " + i; step = "monkey " + s + ": " + what; await clickEl(unitRow(i)); }
    else if (r < 0.62) { const [x, y] = await at(rnd(), rnd()); what = "stage click " + x.toFixed(0) + "," + y.toFixed(0); step = "monkey " + s + ": " + what; await click(x, y, rnd() < 0.15 ? 2 : 1); }
    else if (r < 0.70) { const [x, y] = await at(rnd(), rnd()); const [x2, y2] = await at(rnd(), rnd()); what = "drag"; step = "monkey " + s + ": " + what;
      await mouse("mouseMoved", x, y); await mouse("mousePressed", x, y); for (let k = 1; k <= 5; k++) await mouse("mouseMoved", x + (x2 - x) * k / 5, y + (y2 - y) * k / 5, { buttons: 1 }); await mouse("mouseReleased", x2, y2); }
    else if (r < 0.78) { const [x, y] = await at(rnd(), rnd()); what = "wheel"; step = "monkey " + s + ": " + what; await send("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: 0, deltaY: (rnd() - 0.5) * 800 }); }
    else if (r < 0.88) { const id = pick(ranges); const v = rnd(); what = "range " + id + "=" + v.toFixed(2); step = "monkey " + s + ": " + what;
      await ev(`(()=>{const e=document.querySelector('${id}'); if(!e) return; const lo=+e.min||0, hi=+e.max||100; e.value=lo+${v}*(hi-lo); e.dispatchEvent(new Event('input')); e.dispatchEvent(new Event('change'))})()`); }
    else { const k = pick(["Escape", "Delete", "Enter", " ", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Backspace"]); what = "key " + JSON.stringify(k); step = "monkey " + s + ": " + what; await key(k); }
    await sleep(60 + rnd() * 200);
    if (s % 5 === 4) await invariants();
  }
  step = "end"; await sleep(1500); await invariants();
  await ev("ROIS.length=0; saveRois && saveRois(); 'ok'");
  console.log(`\n${issues.length} issue(s), seed ${SEED}:`);
  for (const i of issues) console.log(`- [${i.kind}] ${i.msg}\n    at: ${i.step}`);
  ch.kill(); process.exit(0);
})();
