/* Display modes in 3D are transparent, in a real Chrome (the same CDP harness as the other checks):
   the floor and the ceiling only say what is shown and never rescale the brightness of the rest; a
   floor set for a channel in the overlay is that channel's floor alone when one channel is shown;
   and a control that changes something besides itself (the auto floor following the mode, a slab
   drawing glass as a MIP) says so in a note over the view.

     python tools/make_synthetic.py --stack synthetic_stack.mesc
     mesc-io view synthetic_stack.mesc --port 8032 --no-browser &
     node tests/view_modes_real_chrome.js http://127.0.0.1:8032/ <out prefix>  */
const { spawn } = require("node:child_process"); const http = require("node:http"); const fs = require("node:fs");
const URL_ = process.argv[2], OUT = process.argv[3];
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9357;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data",d=>b+=d); r.on("end",()=>res(JSON.parse(b))); }).on("error", rej));
(async () => {
  const chrome = spawn(CHROME, ["--headless=new","--remote-debugging-port="+PORT,"--no-first-run","--user-data-dir=/tmp/modes_profile","--window-size=1500,1000","--enable-unsafe-swiftshader","--use-angle=swiftshader","about:blank"], {stdio:"ignore"});
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
  const shot = async name => { const s = await send("Page.captureScreenshot",{format:"png"}); fs.writeFileSync(`${OUT}_${name}.png`, Buffer.from(s.result.data,"base64")); };
  const loaded = async () => { await sleep(300); for (let i=0;i<60 && (await ev("!!volLoading || !volMeta")); i++) await sleep(250); await sleep(300); };
  // the 3D picture's grey levels, read in the same task as the draw
  const pix = () => J(`(()=>{volDraw(); const c=document.getElementById('vol'), t=document.createElement('canvas'); t.width=c.width; t.height=c.height;
    const g=t.getContext('2d'); g.drawImage(c,0,0); return Array.from(g.getImageData(0,0,c.width,c.height).data.filter((_,i)=>i%4===1));})()`);
  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.navigate",{url:URL_}); await sleep(2500);
  await ev("V.flipY=false; V.overlay=false; V.ch=0; V.vol = volState(null); V.vol.on = true; V.vol.mode='mip'; V.vol.cut=true; V.vol.ceil=1; volShow(); volReset(); 'ok'");
  await loaded();
  if (await ev("!!volMeta && !volMeta.ov") !== true) fail("one-channel stack did not load");
  // 1. the ceiling does not rescale: pixels below it keep their grey when it comes down
  await ev("V.vol.thr = 0.0; V.vol.thrFor = unit.path; 'ok'");
  const a = await pix();
  await ev("V.vol.ceil = 0.8; 'ok'"); const b = await pix();
  const lim = 0.8 * 255 * (await ev("V.vol.gain")) * 0.9;   // well below where the ceiling bites, on the screen's scale
  let same = 0, n = 0, worst = 0;
  for (let i = 0; i < a.length; i++) if (a[i] > 20 && a[i] < Math.min(lim, 200)) { n++; const d = Math.abs(a[i] - b[i]); if (d <= 2) same++; worst = Math.max(worst, d); }
  console.log("  ceiling 1 -> 0.8: pixels below it", n, "unchanged", same, "worst", worst);
  if (!n || same / n < 0.97) fail("lowering the ceiling changed the brightness of what is below it");
  // and the floor: what is above it keeps its grey too
  await ev("V.vol.ceil = 1; 'ok'"); const c0 = await pix();
  await ev("V.vol.thr = 0.3; 'ok'"); const c1 = await pix();
  let n2 = 0, s2 = 0; for (let i = 0; i < c0.length; i++) if (c0[i] > 0.45 * 255 * (await 1) && c0[i] < 250) { n2++; if (Math.abs(c0[i] - c1[i]) <= 4) s2++; }
  console.log("  floor 0 -> 0.3: bright pixels", n2, "within 4 grey levels", s2);
  if (!n2 || s2 / n2 < 0.99) fail("raising the floor changed the brightness of what is above it");
  // 2. a mode switch with an auto floor says what it did
  await ev("V.vol.thrFor = ''; V.vol.thr = volAutoThr(); $('volNote').hidden = true; 'ok'");
  await ev("$('volGlass').click(); 'ok'"); await sleep(400);
  const note = await ev("$('volNote').hidden ? '' : $('volNote').textContent");
  console.log("  note after MIP -> glass:", JSON.stringify(note));
  if (!/floor ch0:/.test(note) || !/follows the mode/.test(note)) fail("the auto floor changed with the mode without a word");
  await shot("glass_note");
  // 3. a floor set for a channel in the overlay is that channel's floor alone
  await ev("$('volMip').click(); 'ok'"); await sleep(200);
  await ev("$('ovBtn').click(); 'ok'"); await loaded();
  if (!(await ev("!!(volMeta && volMeta.ov)"))) fail("the overlay did not load");
  await ev("V.vol.thrC[0] = 0.33; V.vol.thrCFor = unit.path; volChRows(); volDraw(); $('volNote').hidden = true; 'ok'");
  await ev("$('ovBtn').click(); 'ok'"); await loaded();
  const after = await J("({thr: V.vol.thr, by: V.vol.thrFor === unit.path, ov: volOv()})");
  const note2 = await ev("$('volNote').hidden ? '' : $('volNote').textContent");
  console.log("  overlay -> one channel:", JSON.stringify(after), "note:", JSON.stringify(note2));
  if (after.ov || Math.abs(after.thr - 0.33) > 1e-9 || !after.by) fail("the channel's floor from the overlay did not carry over");
  if (/floor ch0:/.test(note2)) fail("the note claims the floor changed when it was carried over");
  // 4. slab turns glass into MIP — and says so
  await ev("$('volGlass').click(); 'ok'"); await sleep(200); await ev("$('volNote').hidden = true; $('volSlab').click(); 'ok'"); await sleep(400);
  const note3 = await ev("$('volNote').hidden ? '' : $('volNote').textContent");
  console.log("  slab on glass:", JSON.stringify(note3));
  if (!/mode: glass → MIP/.test(note3)) fail("slab switched glass to MIP without a word");
  await shot("slab_note");
  console.log("  console errors:", errors.length, errors.slice(0, 3));
  if (errors.length) fail("console errors");
  console.log("  modes: ok"); chrome.kill(); process.exit(0);
})();
