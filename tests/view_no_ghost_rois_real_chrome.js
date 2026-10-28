/* The 2D image's gestures stay on the 2D image, in a real Chrome: clicking every button of the 3D
   and XYZ bars puts down no ROI (the 3D bar sits inside the stage, and its clicks used to reach
   the hidden 2D image and leave spot ROIs in the ROI file), Backspace under a 3D view deletes no
   ROI it cannot show, and in 2D a click still puts a spot down.

     python tools/make_synthetic.py --stack synthetic_stack.mesc
     HOME=<scratch> mesc-io view synthetic_stack.mesc --port 8032 --no-browser &
     node tests/view_no_ghost_rois_real_chrome.js http://127.0.0.1:8032/ <out prefix>  */
const { spawn } = require("node:child_process"); const http = require("node:http");
const URL_ = process.argv[2];
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9361;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data",d=>b+=d); r.on("end",()=>res(JSON.parse(b))); }).on("error", rej));
(async () => {
  const chrome = spawn(CHROME, ["--headless=new","--remote-debugging-port="+PORT,"--no-first-run","--user-data-dir=/tmp/ghost_profile","--window-size=1280,800","--enable-unsafe-swiftshader","--use-angle=swiftshader","about:blank"], {stdio:"ignore"});
  process.on("exit", () => { try { chrome.kill(); } catch(_){} });
  let t; for (let i=0;i<30;i++){ try { t = await getJSON(`http://127.0.0.1:${PORT}/json`); break; } catch { await sleep(300);} }
  const ws = new WebSocket(t.find(x=>x.type==="page").webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let id=0; const pend=new Map(); const errors=[];
  ws.onmessage = m => { const d=JSON.parse(m.data); if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); }
    else if (d.method==="Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description||d.params.exceptionDetails.text); };
  const send=(m,p={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}));});
  const ev=async e=>{const r=await send("Runtime.evaluate",{expression:e,returnByValue:true,awaitPromise:true});
    if(r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description||r.result.exceptionDetails.text); return r.result.result.value;};
  const J = async e => JSON.parse(await ev(`JSON.stringify(${e})`));
  const fail = m => { console.log("  FAIL: " + m); chrome.kill(); process.exit(1); };
  const click = async (x, y) => { for (const type of ["mouseMoved","mousePressed","mouseReleased"]) await send("Input.dispatchMouseEvent",{type,x,y,button:"left",clickCount:1}); await sleep(320); };
  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.navigate",{url:URL_}); await sleep(2500);
  await ev("ROIS.length = 0; renderRois(); saveRois(); V.vol = volState(null); V.vol.on = true; volShow(); volReset(); 'ok'");
  for (let i = 0; i < 40 && !(await ev("!!volMeta")); i++) await sleep(250);
  await sleep(400);
  // every visible button of the 3D bar, clicked with real mouse events (a second click undoes a toggle)
  const btns = await J(`[...document.querySelectorAll('#volBar button')].filter(b => b.offsetParent !== null).map(b => { const r = b.getBoundingClientRect(); return {id: b.id || b.textContent.trim(), x: r.left + r.width / 2, y: r.top + r.height / 2}; })`);
  if (btns.length < 8) fail("too few 3D buttons found: " + btns.length);
  for (const b of btns) { await click(b.x, b.y); await click(b.x, b.y); }
  await sleep(500);
  let n = await ev("ROIS.length");
  if (n !== 0) fail(`${n} ROI(s) put down by clicking the 3D bar's buttons`);
  // Backspace under 3D: an ROI made in 2D is still there after it
  await ev("V.vol.on = false; V.vol.ortho = false; volShow(); paint(); 'ok'"); await sleep(300);
  const c = await J("(()=>{const r=document.getElementById('view').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2};})()");
  await click(c.x, c.y); await sleep(400);
  n = await ev("ROIS.length");
  if (n !== 1) fail("a click on the 2D image did not put a spot down (got " + n + ")");
  await ev("V.sel = 0; V.vol.on = true; volShow(); document.activeElement && document.activeElement.blur(); 'ok'"); await sleep(400);
  await send("Input.dispatchKeyEvent", {type: "keyDown", key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8}); await sleep(300);
  if (await ev("ROIS.length") !== 1) fail("Backspace under the 3D view deleted an ROI");
  // XYZ bar too
  await ev("V.vol.on = false; V.vol.ortho = true; volShow(); 'ok'"); await sleep(500);
  const ob = await J(`[...document.querySelectorAll('#ortho button')].filter(b => b.offsetParent !== null && b.id !== 'oSurf').map(b => { const r = b.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })`);
  for (const b of ob) { await click(b.x, b.y); await click(b.x, b.y); }
  if (await ev("ROIS.length") !== 1) fail("the XYZ bar's buttons changed the ROIs");
  await ev("ROIS.length = 0; renderRois(); saveRois(); 'ok'");
  console.log(`  no ghost ROIs: ${btns.length} 3D buttons and ${ob.length} XYZ buttons clicked twice each, Backspace under 3D — ok; console errors: ${errors.length}`, errors.slice(0, 3));
  if (errors.length) fail("console errors");
  chrome.kill(); process.exit(0);
})();
