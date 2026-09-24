/* A z-stack in a real Chrome: the slider must count slices in microns, not frames in seconds,
   and max must differ from mean — on a stack a bouton lives in three slices of thirty and an
   average dilutes it. Same CDP harness as the other real-browser checks, no puppeteer. */
const { spawn } = require("node:child_process"); const http = require("node:http");
const URL_ = process.argv[2], OUT = process.argv[3];
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9339;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data",d=>b+=d); r.on("end",()=>res(JSON.parse(b))); }).on("error", rej));
(async () => {
  const chrome = spawn(CHROME, ["--headless=new","--remote-debugging-port="+PORT,"--no-first-run",
    "--user-data-dir=/tmp/zstack_profile","--window-size=1500,1000","about:blank"], {stdio:"ignore"});
  process.on("exit", () => { try { chrome.kill(); } catch(_){} });
  let t; for (let i=0;i<30;i++){ try { t = await getJSON(`http://127.0.0.1:${PORT}/json`); break; } catch { await sleep(300);} }
  const ws = new WebSocket(t.find(x=>x.type==="page").webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id=0; const pend=new Map(); const errors=[];
  ws.onmessage = m => { const d=JSON.parse(m.data);
    if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); }
    else if (d.method==="Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description||d.params.exceptionDetails.text); };
  const send=(m,p={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}));});
  const ev=async e=>{const r=await send("Runtime.evaluate",{expression:e,returnByValue:true,awaitPromise:true});
    if(r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text); return r.result.result.value;};
  const click=async sel=>{const b=JSON.parse(await ev(`JSON.stringify(document.querySelector('${sel}').getBoundingClientRect())`));
    if(!b.width) throw new Error("no such control: "+sel);
    await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:b.x+b.width/2,y:b.y+b.height/2,button:"left"});
    await send("Input.dispatchMouseEvent",{type:"mousePressed",x:b.x+b.width/2,y:b.y+b.height/2,button:"left",clickCount:1});
    await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:b.x+b.width/2,y:b.y+b.height/2,button:"left",clickCount:1});
    await sleep(900);};
  const fail=m=>{console.error("  FAIL: "+m); chrome.kill(); process.exit(1);};
  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.navigate",{url:URL_}); await sleep(2200);

  // the z-stack units are the ones the reader gave no frame rate
  const stack = await ev("FILE.units.findIndex(u => u.z_step_um)");
  if (stack < 0) fail("no z-stack in this file");
  await ev(`pick(${stack}); 'ok'`); await sleep(1400);
  const u = JSON.parse(await ev("JSON.stringify({z:unit.z_step_um,fs:unit.frame_rate_hz,n:unit.frames,p:unit.path})"));
  if (u.fs !== null) fail("a stack was given a frame rate: " + u.fs);

  await ev("V.proj=''; draw(); 'ok'"); await sleep(700);
  const lbl = await ev("document.getElementById('frameLbl').textContent");
  if (!/µm/.test(lbl) || /\bs\b/.test(lbl)) fail("the slider does not speak microns: " + lbl);

  await click("#maxBtn");
  const maxLbl = await ev("document.getElementById('frameLbl').textContent");
  const maxUrl = await ev("imgUrl");
  if (!/mode=max/.test(maxUrl)) fail("max did not ask for a max projection: " + maxUrl);
  await click("#meanBtn");
  const meanUrl = await ev("imgUrl");
  if (!/mode=mean/.test(meanUrl)) fail("mean did not ask for a mean projection: " + meanUrl);
  await click("#meanBtn");                                  // the active one returns to slices
  if (await ev("V.proj") !== "") fail("clicking the active projection did not return to slices");

  // the two projections are genuinely different pictures
  const px = async mode => await ev(`(async()=>{const r=await fetch('/api/mean/${u.p}/0?lo=1&hi=99.5&mode=${mode}');
      const b=await r.arrayBuffer(); return b.byteLength;})()`);
  const a = await px("mean"), b = await px("max");
  if (a === b) fail("mean and max returned identical bytes");

  await click("#maxBtn");
  const shot = await send("Page.captureScreenshot",{format:"png"});
  require("node:fs").writeFileSync(OUT, Buffer.from(shot.result.data,"base64"));
  console.log("  стек:", u.p, "·", u.n, "зрізів ·", u.z, "мкм/зріз · fs:", u.fs);
  console.log("  підпис зрізу:", lbl);
  console.log("  підпис проєкції:", maxLbl);
  console.log("  mean vs max, байтів:", a, "vs", b);
  console.log("  помилок у консолі:", errors.length, errors.slice(0,2));
  chrome.kill(); process.exit(errors.length ? 1 : 0);
})();
