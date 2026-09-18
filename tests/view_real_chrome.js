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
  const saved = await getJSON(URL_ + "api/rois?unit=" + encodeURIComponent(await ev("unit.path")));
  if (Math.abs(saved.rois[0].points[0][0] - c1[0]) > 0) fail("the moved ROI was not saved");
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
  const y = tr.top + tr.height / 2, x0 = tr.left + 200, x1 = tr.left + 500;
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
  await drag(tr.left + 300, tr.top + tr.height * 0.3, tr.left + 600, tr.top + tr.height * 0.7);
  const vz = JSON.parse(await ev("JSON.stringify(V.valueZoom)")); console.log("  overlay valueZoom:", vz);
  if (!vz) fail("overlay box did not crop the value range");
  // double-click on the traces: home, and the frame does not jump twice on the way
  const fBefore = await ev("V.frame");
  const dx = tr.left + 450, dy = tr.top + tr.height / 2;
  await mouse("mouseMoved", dx, dy);
  await mouse("mousePressed", dx, dy, { clickCount: 1 }); await mouse("mouseReleased", dx, dy, { clickCount: 1 });
  await mouse("mousePressed", dx, dy, { clickCount: 2 }); await mouse("mouseReleased", dx, dy, { clickCount: 2 }); await sleep(450);
  if (await ev("V.traceZoom") !== null || await ev("V.valueZoom") !== null) fail("double-click on the traces did not go home");
  if (await ev("V.frame") !== fBefore) fail("the double-click's clicks jumped the frame");
  console.log("  traces double-click: home, frame untouched");
  // the y limits adapt: a value box is dropped as soon as the time window moves
  await drag(tr.left + 300, tr.top + tr.height * 0.3, tr.left + 600, tr.top + tr.height * 0.7);
  if (await ev("V.valueZoom") === null) fail("expected a value box before sliding");
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 }); await sleep(100);
  if (await ev("V.valueZoom") !== null) fail("the value box survived a change of the time window");
  console.log("  y limits adapt after the window moves");
  await ev("document.getElementById('traceReset').click(); 'ok'");

  // 2b. keys: with a time zoom, → slides the window; a click on a ROW then Delete removes the ROI
  await ev("V.traceZoom=[100,200]; plotTraces(); 'ok'");
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 }); await sleep(100);
  const slid = JSON.parse(await ev("JSON.stringify(V.traceZoom)")); console.log("  → slid window:", slid);
  if (slid[0] !== 110 || slid[1] !== 210) fail("ArrowRight did not slide the zoom window by 10%");
  const row = JSON.parse(await ev("JSON.stringify(document.querySelector('#roiList .r[data-i]').getBoundingClientRect())"));
  await mouse("mouseMoved", row.left + row.width / 2, row.top + row.height / 2);
  await mouse("mousePressed", row.left + row.width / 2, row.top + row.height / 2, { clickCount: 1 });
  await mouse("mouseReleased", row.left + row.width / 2, row.top + row.height / 2, { clickCount: 1 }); await sleep(100);
  if (await ev("V.sel") < 0) fail("clicking the row did not select the ROI");
  const nBefore = await ev("ROIS.length");
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Delete", code: "Delete", windowsVirtualKeyCode: 46 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Delete", code: "Delete", windowsVirtualKeyCode: 46 }); await sleep(200);
  const nAfter = await ev("ROIS.length"); console.log("  Delete after a row click:", nBefore, "->", nAfter);
  if (nAfter !== nBefore - 1) fail("Delete did not remove the selected ROI");
  await ev("addRoi({name:'roi9', points: disc(60,60)}); 'ok'"); await sleep(100);
  // Enter with ROIs present computes the traces
  if (await ev("TR") !== null) fail("expected TR null after adding an ROI");
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 }); await sleep(2000);
  if (await ev("TR ? TR.names.length : 0") < 1) fail("Enter did not compute the traces");
  console.log("  Enter: traces computed");

  const pickUnit = async (i) => { await ev(`document.body.dataset.roisFor=''; document.querySelectorAll('.u')[${i}].click(); 'ok'`);
    for (let k = 0; k < 40; k++) { await sleep(100); if (await ev("document.body.dataset.roisFor === unit.path")) return; } fail("unit " + i + " never finished loading its ROIs"); };
  // 2c. ROIs belong to the unit: draw on unit 0, switch to unit 1 -> empty; copy from -> present; back -> intact
  await pickUnit(1);
  await ev("ROIS.length=0; saveRois(); 'ok'"); await sleep(300);         // a previous run may have left a set here
  await pickUnit(0);
  await ev("ROIS.length=0; addRoi({name:'a', points: disc(30,40)}); addRoi({name:'b', points: disc(70,60)}); 'ok'");
  for (let k = 0; k < 40; k++) { await sleep(100); if (await ev("ROI_UNITS[unit.path] === 2")) break; }   // both saves acknowledged
  await pickUnit(1);
  const n1 = await ev("ROIS.length"); const menu = await ev("document.getElementById('copyFrom').style.display");
  console.log("  unit 1 rois:", n1, "copy menu shown:", menu === "");
  if (n1 !== 0) fail("unit 1 sees unit 0's ROIs");
  if (menu !== "") fail("the copy-from menu is hidden although unit 0 has ROIs");
  await ev("const c=document.getElementById('copyFrom'); c.value='MSession_0/MUnit_0'; c.dispatchEvent(new Event('change')); 'ok'"); await sleep(800);
  if (await ev("ROIS.length") !== 2) fail("copy from unit 0 did not bring 2 ROIs");
  await ev("delRoi(0); 'ok'"); await sleep(400);
  await pickUnit(0);
  if (await ev("ROIS.length") !== 2) fail("deleting on unit 1 touched unit 0's set");
  console.log("  per-unit ROIs: independent, copy works");
  await pickUnit(1);
  await ev("ROIS.length=0; saveRois(); addRoi({name:'roi9', points: disc(60,60)}); 'ok'"); await sleep(400);

  // 2d. spot radius and rect size: typed for new ones, and changed on the selected one
  await ev("ROIS.length=0; saveRois(); document.getElementById('spotR').value='5'; setTool('spot'); 'ok'");
  const [px, py] = await at(40, 90);
  await mouse("mouseMoved", px, py); await mouse("mousePressed", px, py, { clickCount: 1 }); await mouse("mouseReleased", px, py, { clickCount: 1 }); await sleep(400);
  const r0 = await ev("ROIS[0].r"); if (r0 !== 5) fail("a new spot did not take the typed radius: " + r0);
  await ev("document.getElementById('spotR').value='9'; applySize(); 'ok'"); await sleep(300);
  const r1 = await ev("ROIS[0].r"), span = await ev("(()=>{const xs=ROIS[0].points.map(p=>p[0]);return Math.max(...xs)-Math.min(...xs)})()");
  console.log("  spot r:", r0, "->", r1, "point span:", span);
  if (r1 !== 9 || Math.abs(span - 18) > 0.5) fail("resizing the selected spot did not regenerate its points");
  await ev("setTool('rect'); document.getElementById('rectW').value='12'; document.getElementById('rectH').value='6'; 'ok'");
  const [qx2, qy2] = await at(90, 30);
  await mouse("mouseMoved", qx2, qy2); await mouse("mousePressed", qx2, qy2, { clickCount: 1 }); await mouse("mouseReleased", qx2, qy2, { clickCount: 1 }); await sleep(400);
  const rk = await ev("ROIS[1] && ROIS[1].kind"), rw = await ev("ROIS[1] && ROIS[1].w");
  console.log("  rect placed:", rk, rw + "x" + await ev("ROIS[1].h"));
  if (rk !== "rect" || rw !== 12) fail("the rect tool did not place a 12x6 rect");
  // dragging the rect moves its centre and its points together
  const [dx0, dy0] = await at(90, 30), [dx1, dy1] = await at(100, 30);
  await drag(dx0, dy0, dx1, dy1);
  const cx = await ev("ROIS[1].cx"), p0 = await ev("ROIS[1].points[0][0]");
  if (Math.abs(cx - 100) > 1 || Math.abs(p0 - 94) > 1) fail("dragging the rect did not move centre and points together: " + cx + " " + p0);
  console.log("  rect dragged: cx", cx, "first corner x", p0);
  // the size row follows the selection
  await ev("V.sel=0; renderRois(); 'ok'");
  if (await ev("document.getElementById('sizeWho').textContent") !== "size of roi1") fail("size row does not follow the selection");
  await ev("setTool('spot'); ROIS.length=0; saveRois(); addRoi(makeSpot(60,60,3)); 'ok'"); await sleep(300);

  // 2e. the metadata panel resizes from its top edge, like the trace strip, and the height is saved
  const ms = JSON.parse(await ev("JSON.stringify(document.getElementById('metaSplit').getBoundingClientRect())"));
  await ev("V.metaH=300; applyStatic(); 'ok'"); await sleep(100);               // a previous run may have left it near the clamp
  const ms2 = JSON.parse(await ev("JSON.stringify(document.getElementById('metaSplit').getBoundingClientRect())"));
  const h0 = await ev("V.metaH");
  await drag(ms2.left + 100, ms2.top + 2, ms2.left + 100, ms2.top - 80);
  const h1 = await ev("V.metaH"), css = await ev("getComputedStyle(document.getElementById('meta')).height");
  console.log("  metadata panel:", h0, "->", h1, "px, css", css);
  if (Math.abs((h1 - h0) - 80) > 3) fail("dragging the metadata splitter did not grow the panel by the drag");
  await sleep(500);
  const savedH = (await getJSON(URL_ + "api/view")).view.metaH; if (savedH !== h1) fail("the metadata height was not saved: " + savedH);

  // 2f. typed vertical limits: apply in both modes, survive a time zoom, 'auto' releases them
  await ev("document.getElementById('doTraces').click(); 'ok'"); for (let i = 0; i < 40; i++) { await sleep(250); if (await ev("TR !== null")) break; }
  await ev("V.traceZoom=null; V.valueZoom=null; V.yFixed=null; document.getElementById('modeOverlay').click(); 'ok'"); await sleep(200);
  const autoPh = await ev("document.getElementById('yLo').placeholder");
  await ev("(()=>{const a=document.getElementById('yLo'), b=document.getElementById('yHi'); a.value='-400'; b.value='-100'; b.dispatchEvent(new Event('change'));})(); 'ok'"); await sleep(200);
  let yf = JSON.parse(await ev("JSON.stringify(V.yFixed)")); console.log("  y typed:", yf, "(auto was", autoPh + ")");
  if (!yf || yf[0] !== -400 || yf[1] !== -100) fail("typed y limits were not applied");
  if (autoPh === "auto") fail("the auto placeholder did not show the limits in force");
  await ev("V.traceZoom=[100,300]; plotTraces(); 'ok'"); await sleep(100);
  if (!(await ev("V.yFixed"))) fail("a time zoom dropped the typed limits");
  await ev("document.getElementById('modeStack').click(); 'ok'"); await sleep(100);
  if (!(await ev("V.yFixed"))) fail("switching to stack dropped the typed limits");
  await ev("(()=>{const a=document.getElementById('yLo'), b=document.getElementById('yHi'); a.value='0'; b.value='-5'; b.dispatchEvent(new Event('change'));})(); 'ok'"); await sleep(100);
  yf = JSON.parse(await ev("JSON.stringify(V.yFixed)")); if (yf[0] !== -400) fail("an inverted range was accepted");
  await ev("document.getElementById('yAuto').click(); 'ok'"); await sleep(100);
  if (await ev("V.yFixed") !== null) fail("'auto' did not release the limits");
  if (await ev("document.getElementById('yLo').value") !== "") fail("the boxes did not clear on auto");
  console.log("  y limits: typed, kept across zoom and mode, inverted refused, auto releases");
  await ev("document.getElementById('traceReset').click(); 'ok'");

  // 2g. hover readouts: the pixel under the cursor on the image, the value under it on a trace
  await ev("V.mean=true; applyStatic(); draw(); 'ok'"); await sleep(300);
  const [hx, hy] = await at(30, 40);
  await mouse("mouseMoved", hx, hy); await sleep(400);
  const pr = await ev("document.getElementById('pixelRead').textContent");
  console.log("  pixel readout:", pr);
  if (!/x 30 · y 40 · \S+/.test(pr) || !/\(3×3/.test(pr)) fail("no pixel value in the image readout: " + pr);
  const tr2 = JSON.parse(await ev("JSON.stringify(document.getElementById('trace').getBoundingClientRect())"));
  await mouse("mouseMoved", tr2.left + 400, tr2.top + tr2.height / 2); await sleep(100);
  const trr = await ev("document.getElementById('traceRead').textContent");
  console.log("  trace readout:", trr);
  if (!/frame \d+/.test(trr) || !/ s · -?[\d.]+$/.test(trr)) fail("no value in the trace readout: " + trr);
  await mouse("mouseMoved", 5, 5);

  // 3. AVG typed as a number
  await ev("const a=document.getElementById('avgN'); a.value='13'; a.dispatchEvent(new Event('change')); 'ok'"); await sleep(400);
  const avg = await ev("V.avg"); const url = await ev("frameUrl()");
  console.log("  avg:", avg, "url:", url);
  if (avg !== 13 || !/n=13/.test(url)) fail("typed AVG did not reach the request");
  console.log(errors.length ? "\n  ERRORS: " + errors.join(" | ") : "\n  drag / box / typed-AVG OK in real Chrome");
  ws.close(); chrome.kill();
})().catch(e => { console.error("ERR", e); process.exit(1); });
