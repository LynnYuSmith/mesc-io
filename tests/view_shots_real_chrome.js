"use strict";
/* Screenshots of the viewer's states in a real Chrome over CDP, plus a console-error check.
   NOT collected by pytest.  node tests/view_shots_real_chrome.js <url> <outdir> */
   state, and report any console error. node view_shot.js <url> <outdir> */
const { spawn } = require("node:child_process");
const http = require("node:http"); const fs = require("node:fs"); const path = require("node:path");
const URL_ = process.argv[2], OUT = process.argv[3];
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9335;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const getJSON = (u) => new Promise((res, rej) => http.get(u, r => { let b = ""; r.on("data", d => b += d); r.on("end", () => res(JSON.parse(b))); }).on("error", rej));
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=" + PORT, "--no-first-run",
    "--user-data-dir=/tmp/view_chrome_profile", "--window-size=1440,900", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
  let targets; for (let i = 0; i < 30; i++) { try { targets = await getJSON(`http://127.0.0.1:${PORT}/json`); break; } catch { await sleep(300); } }
  const ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0; const pending = new Map(); const errors = [];
  ws.onmessage = (m) => { const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    else if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
    else if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") errors.push(d.params.args.map(a => a.value || a.description).join(" ")); };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }); return r.result && r.result.result ? r.result.result.value : r; };
  const shot = async (name) => { const r = await send("Page.captureScreenshot", { format: "png" }); fs.writeFileSync(path.join(OUT, name + ".png"), Buffer.from(r.result.data, "base64")); console.log("  shot", name); };
  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.navigate", { url: URL_ }); await sleep(1800);
  await shot("1_open");
  // add three spots on the known boutons: image coords -> stage coords through the page's own mapping
  await ev(`(()=>{ const m = mapping(); const st=document.getElementById('stage').getBoundingClientRect();
     for (const [x,y] of [[30,40],[70,60],[95,90]]) { const ev = {clientX: st.left + m.ox + (x+.5)*m.k, clientY: st.top + m.oy + (y+.5)*m.k};
       document.getElementById('stage').onclick(ev); } return ROIS.length })()`);
  await sleep(300);
  await ev("document.getElementById('doTraces').click(); 'ok'"); await sleep(2500);
  await shot("2_rois_traces_stack");
  await ev("document.getElementById('modeOverlay').click(); 'ok'"); await sleep(200);
  await shot("3_overlay");
  await ev("document.getElementById('modeStack').click(); V.zoom={x:20,y:30,w:60,h:50}; paint(); V.traceZoom=[200,500]; plotTraces(); V.frame=350; document.getElementById('frame').value=350; V.mean=false; draw(); plotTraces(); 'ok'"); await sleep(400);
  await shot("4_zoomed_image_and_time");
  await ev("stepAvg(3); 'ok'"); await sleep(400);
  await shot("5_avg8");
  await ev("document.querySelectorAll('.u')[2].click(); 'ok'"); await sleep(900);
  await shot("6_unit3");
  const saved = await ev("fetch('/api/view').then(r=>r.json()).then(d=>JSON.stringify(d.view))");
  console.log("  saved view:", saved.slice(0, 200));
  console.log(errors.length ? "\n  CONSOLE ERRORS:\n  " + errors.join("\n  ") : "\n  no console errors");
  ws.close(); chrome.kill();
})().catch(e => { console.error("ERR", e); process.exit(1); });
