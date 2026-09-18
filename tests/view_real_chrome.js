"use strict";
/* Real-mouse checks of the viewer over CDP -- a real Chrome, no puppeteer, node's built-in
   WebSocket. NOT collected by pytest: needs Chrome and a running `mesc-io view` on a file.

     mesc-io view tests/…/synthetic.mesc --port 8031 --no-browser &
     node tests/view_real_chrome.js http://127.0.0.1:8031/

   What is held: a click adds a spot; a double-click resets the zoom and adds NOTHING (the
   click waits a beat and the double-click cancels it); a drag on an ROI moves it and the
   move reaches the server; a click on an ROI selects and does not add; a drag on empty image
   is the zoom box; a drag on the traces shows a rubber band and zooms time, and in overlay
   also crops the value range; AVG typed as a number reaches the request. */
const { spawn } = require("node:child_process"); const http = require("node:http"); const fs = require("node:fs");
const URL_ = process.argv[2]; const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9336;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const getJSON = (u) => new Promise((res, rej) => http.get(u, r => { let b = ""; r.on("data", d => b += d); r.on("end", () => res(JSON.parse(b))); }).on("error", rej));
(async () => {
  const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=" + PORT, "--no-first-run", "--user-data-dir=/tmp/view_drag_profile", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
  let targets; for (let i = 0; i < 30; i++) { try { targets = await getJSON(`http://127.0.0.1:${PORT}/json`); break; } catch { await sleep(300); } }
  const ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let id = 0; const pending = new Map(); const errors = [];
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    else if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text); };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text + " " + (r.result.exceptionDetails.exception||{}).description); return r.result.result.value; };
  const mouse = async (type, x, y, extra = {}) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", ...extra });
  const drag = async (x0, y0, x1, y1) => { await mouse("mouseMoved", x0, y0); await mouse("mousePressed", x0, y0, { clickCount: 1 });
    for (let k = 1; k <= 8; k++) { await mouse("mouseMoved", x0 + (x1 - x0) * k / 8, y0 + (y1 - y0) * k / 8, { buttons: 1 }); await sleep(15); }
    await mouse("mouseReleased", x1, y1, { clickCount: 1 }); await sleep(150); };
  const fail = (m) => { console.error("  FAIL: " + m); chrome.kill(); process.exit(1); };
  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.navigate", { url: URL_ }); await sleep(1800);
  await ev("ROIS.length = 0; V.zoom={x:0,y:0,w:0,h:0}; V.mean=true; V.avg=1; applyStatic(); draw(); 'ok'"); await sleep(300);

  // 1. put one spot by a real click at image (30,40), then drag it by +20 image px in x
  const at = async (x, y) => JSON.parse(await ev(`(()=>{const m=mapping(),st=document.getElementById('stage').getBoundingClientRect();return JSON.stringify([st.left+m.ox+(${x}+.5)*m.k, st.top+m.oy+(${y}+.5)*m.k])})()`));
  let [sx, sy] = await at(30, 40);
  await mouse("mouseMoved", sx, sy); await mouse("mousePressed", sx, sy, { clickCount: 1 }); await mouse("mouseReleased", sx, sy, { clickCount: 1 }); await sleep(400);
  let n = await ev("ROIS.length"); if (n !== 1) fail("click did not add a spot: " + n);
  // a double-click on empty image resets the zoom and adds NOTHING
  await ev("V.zoom={x:10,y:10,w:50,h:50}; paint(); 'ok'");
  const [qx, qy] = await at(20, 20);   // inside the zoom box, away from the spot
  await mouse("mouseMoved", qx, qy);
  await mouse("mousePressed", qx, qy, { clickCount: 1 }); await mouse("mouseReleased", qx, qy, { clickCount: 1 });
  await mouse("mousePressed", qx, qy, { clickCount: 2 }); await mouse("mouseReleased", qx, qy, { clickCount: 2 }); await sleep(450);
  if (await ev("ROIS.length") !== 1) fail("a double-click added spots: " + await ev("ROIS.length"));
  if (await ev("V.zoom.w") !== 0) fail("the double-click did not reset the zoom");
  console.log("  double-click: zoom reset, no spot added");
  const c0 = JSON.parse(await ev("JSON.stringify(ROIS[0].points[0])"));
  let [tx, ty] = await at(50, 40);
  await drag(sx, sy, tx, ty);
  const c1 = JSON.parse(await ev("JSON.stringify(ROIS[0].points[0])"));
  n = await ev("ROIS.length");
  console.log("  spot moved:", c0, "->", c1, "rois:", n);
  if (n !== 1) fail("dragging the spot added an ROI instead of moving it");
  if (Math.abs((c1[0] - c0[0]) - 20) > 1 || Math.abs(c1[1] - c0[1]) > 1) fail("the spot did not move by 20 px in x");
  // the move reached the server
  const saved = await getJSON(URL_ + "api/rois"); if (Math.abs(saved.rois[0].points[0][0] - c1[0]) > 0) fail("the moved ROI was not saved");
  // a click on the moved spot selects it and does NOT add another
  await mouse("mouseMoved", tx, ty); await mouse("mousePressed", tx, ty, { clickCount: 1 }); await mouse("mouseReleased", tx, ty, { clickCount: 1 }); await sleep(150);
  if (await ev("ROIS.length") !== 1) fail("clicking on an ROI added a new one on top");
  if (await ev("V.sel") !== 0) fail("clicking on an ROI did not select it");
  // dragging on EMPTY image still zooms
  const [ex, ey] = await at(90, 90), [fx, fy] = await at(120, 120);
  await drag(ex, ey, fx, fy);
  const z = JSON.parse(await ev("JSON.stringify(V.zoom)")); console.log("  box zoom:", z);
  if (!z.w) fail("a box on empty image did not zoom");
  await sleep(400);
  if (await ev("ROIS.length") !== 1) fail("the zoom drag's release added a spot: " + await ev("ROIS.length"));

  // 2. traces: compute, then drag a box in stack mode -> time zoom, with the rubber shown mid-drag
  await ev("document.getElementById('doTraces').click(); 'ok'"); await sleep(2000);
  const tr = JSON.parse(await ev("JSON.stringify(document.getElementById('trace').getBoundingClientRect())"));
  const y = tr.top + 40, x0 = tr.left + 200, x1 = tr.left + 500;
  await mouse("mouseMoved", x0, y); await mouse("mousePressed", x0, y, { clickCount: 1 });
  await mouse("mouseMoved", x0 + 100, y, { buttons: 1 }); await sleep(50);
  const shown = await ev("document.getElementById('traceRubber').style.display");
  await mouse("mouseMoved", x1, y, { buttons: 1 }); await mouse("mouseReleased", x1, y, { clickCount: 1 }); await sleep(150);
  const tz = JSON.parse(await ev("JSON.stringify(V.traceZoom)"));
  console.log("  rubber mid-drag:", shown, "traceZoom:", tz);
  if (shown !== "block") fail("no rubber band on the traces while dragging");
  if (!tz || tz[1] - tz[0] < 10) fail("trace drag did not zoom in time");
  // overlay: a box also crops the value range
  await ev("document.getElementById('modeOverlay').click(); 'ok'"); await sleep(200);
  await drag(tr.left + 300, tr.top + 60, tr.left + 600, tr.top + 140);
  const vz = JSON.parse(await ev("JSON.stringify(V.valueZoom)")); console.log("  overlay valueZoom:", vz);
  if (!vz) fail("overlay box did not crop the value range");
  // double-click on the traces: home, and the frame does not jump twice on the way
  const fBefore = await ev("V.frame");
  const dx = tr.left + 450, dy = tr.top + 100;
  await mouse("mouseMoved", dx, dy);
  await mouse("mousePressed", dx, dy, { clickCount: 1 }); await mouse("mouseReleased", dx, dy, { clickCount: 1 });
  await mouse("mousePressed", dx, dy, { clickCount: 2 }); await mouse("mouseReleased", dx, dy, { clickCount: 2 }); await sleep(450);
  if (await ev("V.traceZoom") !== null || await ev("V.valueZoom") !== null) fail("double-click on the traces did not go home");
  if (await ev("V.frame") !== fBefore) fail("the double-click's clicks jumped the frame");
  console.log("  traces double-click: home, frame untouched");

  // 3. AVG typed as a number
  await ev("const a=document.getElementById('avgN'); a.value='13'; a.dispatchEvent(new Event('change')); 'ok'"); await sleep(400);
  const avg = await ev("V.avg"); const url = await ev("frameUrl()");
  console.log("  avg:", avg, "url:", url);
  if (avg !== 13 || !/n=13/.test(url)) fail("typed AVG did not reach the request");
  console.log(errors.length ? "\n  ERRORS: " + errors.join(" | ") : "\n  drag / box / typed-AVG OK in real Chrome");
  ws.close(); chrome.kill();
})().catch(e => { console.error("ERR", e); process.exit(1); });
