/* The metadata window, clicked by a real mouse in a real Chrome — same CDP harness as
   tests/view_real_chrome.js, no puppeteer. */
const { spawn } = require("node:child_process"); const http = require("node:http");
const URL_ = process.argv[2]; const OUT = process.argv[3];
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9338;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data",d=>b+=d); r.on("end",()=>res(JSON.parse(b))); }).on("error", rej));
(async () => {
  const chrome = spawn(CHROME, ["--headless=new","--remote-debugging-port="+PORT,"--no-first-run",
    "--user-data-dir=/tmp/meta_profile","--window-size=1500,1000","about:blank"], {stdio:"ignore"});
  process.on("exit", () => { try { chrome.kill(); } catch(_){} });
  let targets; for (let i=0;i<30;i++){ try { targets = await getJSON(`http://127.0.0.1:${PORT}/json`); break; } catch { await sleep(300);} }
  const ws = new WebSocket(targets.find(t=>t.type==="page").webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id=0; const pending=new Map(); const errors=[];
  ws.onmessage = m => { const d=JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    else if (d.method==="Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description||d.params.exceptionDetails.text); };
  const send=(method,params={})=>new Promise(r=>{const i=++id;pending.set(i,r);ws.send(JSON.stringify({id:i,method,params}));});
  const ev=async e=>{const r=await send("Runtime.evaluate",{expression:e,returnByValue:true,awaitPromise:true});
    if(r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text); return r.result.result.value;};
  const mouse=(type,x,y,extra={})=>send("Input.dispatchMouseEvent",{type,x,y,button:"left",...extra});
  const fail=m=>{console.error("  FAIL: "+m); chrome.kill(); process.exit(1);};
  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.navigate",{url:URL_}); await sleep(2000);

  const box = JSON.parse(await ev("JSON.stringify(document.getElementById('allMeta').getBoundingClientRect())"));
  if (!box.width) fail("the all… button is not on the page");
  await mouse("mouseMoved", box.x+box.width/2, box.y+box.height/2);
  await mouse("mousePressed", box.x+box.width/2, box.y+box.height/2, {clickCount:1});
  await mouse("mouseReleased", box.x+box.width/2, box.y+box.height/2, {clickCount:1});
  await sleep(1200);

  const open = await ev("!document.getElementById('allMetaBox').hidden");
  if (!open) fail("the window did not open");
  const title = await ev("document.getElementById('allMetaUnit').textContent");
  const groups = await ev("JSON.stringify([...document.querySelectorAll('#allMetaBody h3')].map(h=>h.textContent))");
  const rows = await ev("document.querySelectorAll('#allMetaBody tr').length");
  if (rows < 50) fail("only "+rows+" rows — the window is not showing everything");

  await ev("const f=document.getElementById('allMetaFilter'); f.value='MESc'; f.dispatchEvent(new Event('input')); 'ok'");
  await sleep(400);
  const filtered = await ev("document.querySelectorAll('#allMetaBody tr').length");
  if (!(filtered > 0 && filtered < rows)) fail("the filter did nothing: "+filtered+" of "+rows);
  const shot = await send("Page.captureScreenshot", {format:"png"});
  require("node:fs").writeFileSync(OUT, Buffer.from(shot.result.data, "base64"));

  await send("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27});
  await send("Input.dispatchKeyEvent",{type:"keyUp",key:"Escape",code:"Escape",windowsVirtualKeyCode:27});
  await sleep(300);
  if (await ev("!document.getElementById('allMetaBox').hidden")) fail("esc did not close it");

  console.log("  відкрилося:", title);
  console.log("  групи:", groups);
  console.log("  рядків:", rows, "· після фільтра «MESc»:", filtered);
  console.log("  esc закриває: так");
  console.log("  помилок у консолі:", errors.length, errors.slice(0,3));
  chrome.kill(); process.exit(errors.length ? 1 : 0);
})();
