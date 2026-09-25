/* A z-stack in 3D, in a real Chrome: WebGL2 must come up, the stack must reach the GPU, the
   first picture must be the stack seen from above (not black), dragging must turn it, depth
   mode must be coloured and glass must show something. Same CDP harness, no puppeteer.
   node tests/view_zstack3d_real_chrome.js <viewer url> <out prefix> */
const { spawn } = require("node:child_process"); const http = require("node:http"); const fs = require("node:fs");
const URL_ = process.argv[2], OUT = process.argv[3];
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9341;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data",d=>b+=d); r.on("end",()=>res(JSON.parse(b))); }).on("error", rej));
(async () => {
  const chrome = spawn(CHROME, ["--headless=new","--remote-debugging-port="+PORT,"--no-first-run",
    "--user-data-dir=/tmp/zstack3d_profile","--window-size=1500,1000","--enable-unsafe-swiftshader",
    "--use-angle=swiftshader","about:blank"], {stdio:"ignore"});
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
    if(r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description||r.result.exceptionDetails.text); return r.result.result.value;};
  const box=async sel=>JSON.parse(await ev(`JSON.stringify(document.querySelector('${sel}').getBoundingClientRect())`));
  const click=async sel=>{const b=await box(sel); if(!b.width) throw new Error("no such control: "+sel);
    for (const type of ["mouseMoved","mousePressed","mouseReleased"])
      await send("Input.dispatchMouseEvent",{type,x:b.x+b.width/2,y:b.y+b.height/2,button:"left",clickCount:1});
    await sleep(700);};
  const fail=m=>{console.error("  FAIL: "+m); chrome.kill(); process.exit(1);};
  // what the canvas shows: mean brightness, and how coloured it is (0 for grey)
  const look = () => ev(`(()=>{const c=document.getElementById('vol'), g=c.getContext('webgl2');
    const w=c.width,h=c.height,p=new Uint8Array(w*h*4); g.readPixels(0,0,w,h,g.RGBA,g.UNSIGNED_BYTE,p);
    let s=0,chroma=0,n=0,peak=0; for(let i=0;i<p.length;i+=4*97){const r=p[i],gg=p[i+1],b=p[i+2]; s+=(r+gg+b)/3; chroma+=Math.max(r,gg,b)-Math.min(r,gg,b); n++;}
    let lit=0, litChroma=0;          // how coloured the OBJECT is: an empty background says nothing
    for(let i=0;i<p.length;i+=4){const v=Math.max(p[i],p[i+1],p[i+2]); if(v>peak) peak=v;
      if(v>60){lit++; litChroma+=v-Math.min(p[i],p[i+1],p[i+2]);}}
    chroma = lit ? litChroma/lit : 0; n = n || 1;
    let sig=0; for(let i=0;i<p.length;i+=4*1013) sig=(sig*31+p[i]+p[i+1]*7+p[i+2]*13)>>>0;
    return {mean:s/n, chroma, lit, peak, sig, w, h};})()`);
  const shot = async name => { const s = await send("Page.captureScreenshot",{format:"png"});
    fs.writeFileSync(`${OUT}_${name}.png`, Buffer.from(s.result.data,"base64")); };
  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.navigate",{url:URL_}); await sleep(2200);

  const stack = await ev("FILE.units.findIndex(u => u.z_step_um)");
  if (stack < 0) fail("no z-stack in this file");
  const rec = await ev("FILE.units.findIndex(u => !u.z_step_um)");
  if (rec >= 0) { await ev(`pick(${rec}); 'ok'`); await sleep(500);
    if (!(await ev("document.getElementById('volBtn').hidden"))) fail("a recording was offered a 3D view"); }
  await ev(`pick(${stack}); V.vol = volState(null); volShow(); 'ok'`); await sleep(900);   // a clean start, not the last run's
  if (await ev("document.getElementById('volBtn').hidden")) fail("a stack was not offered a 3D view");
  await click("#volBtn");
  for (let i = 0; i < 40 && !(await ev("!!volMeta")); i++) await sleep(250);
  if (!(await ev("!!volMeta"))) fail("the stack never reached the GPU: " + await ev("document.getElementById('saveState').textContent"));
  if (await ev("document.getElementById('volBar').hidden")) fail("the 3D controls did not show");
  const meta = JSON.parse(await ev("JSON.stringify(volMeta)"));
  await sleep(400);
  const top = await look();
  if (top.peak < 100) fail("the first 3D picture is black: " + JSON.stringify(top));
  if (Math.abs(await ev("V.vol.yaw")) > 1e-9) fail("the start was not from above");
  await shot("mip_top");

  // turn it by dragging on the canvas
  const b = await box("#vol"), cx = b.x + b.width / 2, cy = b.y + b.height / 2;
  await send("Input.dispatchMouseEvent",{type:"mousePressed",x:cx,y:cy,button:"left",clickCount:1});
  for (let k = 1; k <= 10; k++) await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:cx+k*9,y:cy+k*7,button:"left"});
  await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:cx+90,y:cy+70,button:"left",clickCount:1});
  await sleep(500);
  const ang = JSON.parse(await ev("JSON.stringify({yaw:V.vol.yaw,pitch:V.vol.pitch})"));
  if (Math.abs(ang.yaw) < .5 || Math.abs(ang.pitch) < .4) fail("dragging did not turn it: " + JSON.stringify(ang));
  const turned = await look();
  if (turned.sig === top.sig) fail("turning did not change the picture");
  await shot("mip_turned");

  // The ceiling. Measured where the blobs ARE: the brightest pixels of the full picture. With clip
  // they stay white; with cut they are gone and only what surrounds them is left. Counting lit
  // pixels over the whole frame would not show it: in a MIP the window stretches to floor..ceiling,
  // so cutting the blobs brightens everything under the ceiling.
  const setv = (k, v) => ev(`V.vol.${k} = ${v}; if ("${k}" === "ceil") V.vol.ceilSet = ${v}; volShow(); volDraw(); 'ok'`);
  const grab = () => ev(`(()=>{const c=document.getElementById('vol'),g=c.getContext('webgl2');
    const p=new Uint8Array(c.width*c.height*4); g.readPixels(0,0,c.width,c.height,g.RGBA,g.UNSIGNED_BYTE,p);
    window.__px = p; return p.length;})()`);
  const atBlobs = () => ev(`(()=>{const c=document.getElementById('vol'),g=c.getContext('webgl2');
    const p=new Uint8Array(c.width*c.height*4); g.readPixels(0,0,c.width,c.height,g.RGBA,g.UNSIGNED_BYTE,p);
    let s=0; for (const i of window.__blob) s += p[i]; return s / window.__blob.length;})()`);
  await setv("thr", 0.5); await setv("gain", 1); await setv("ceil", 1); await setv("cut", true); await sleep(200);
  const full = await look(); await grab();
  await ev(`(()=>{const p=window.__px, idx=[]; for(let i=0;i<p.length;i+=4) if(p[i]>=250) idx.push(i);
    window.__blob = idx; return idx.length;})()`);
  const nBlob = await ev("window.__blob.length");
  if (nBlob < 200) fail("no bright blob to test the ceiling on: " + nBlob);
  await setv("ceil", 0.8); await setv("cut", false); await sleep(200);
  const clipped = await atBlobs();
  await setv("cut", true); await sleep(200);
  const cutv = await atBlobs(); await shot("mip_ceiling_cut");
  if (!(clipped > 240)) fail(`clip should hold the blobs at white: ${clipped}`);
  if (!(cutv < clipped * 0.8)) fail(`cut should remove the blobs: ${cutv} vs clip ${clipped}`);
  await setv("cut", false); await sleep(100);
  if (await ev("document.getElementById('volCut').textContent") !== "clip") fail("the cut/clip button does not say which");
  await setv("ceil", 1); await setv("cut", true); await sleep(200);
  if ((await look()).sig !== full.sig) fail("a ceiling of 1 is not the picture it was before the ceiling existed");
  console.log("  ceiling     :", JSON.stringify({ blob_px: nBlob, at_blobs_clip: +clipped.toFixed(1), at_blobs_cut: +cutv.toFixed(1) }));
  await click("#volDepth"); const depth = await look(); await shot("depth_turned");
  if (depth.chroma < 40) fail("depth mode is not coloured: " + JSON.stringify(depth));
  await click("#volGlass"); const glass = await look(); await shot("glass_turned");
  if (glass.peak < 60) fail("glass shows nothing: " + JSON.stringify(glass));
  if (await ev("document.getElementById('volDen').disabled")) fail("density is disabled in glass");

  // the three orthogonal views, from the same bytes
  await click("#orthoBtn");
  if (await ev("document.getElementById('ortho').hidden")) fail("the XYZ views did not show");
  if (!(await ev("document.getElementById('vol').hidden"))) fail("3D and XYZ are both on");
  const g = JSON.parse(await ev("JSON.stringify(oGeom)"));
  const [vz, vy, vx] = meta.vox, [D, Hy, Wx] = meta.shape;
  const want = (D * vz) / (Hy * vy), got = g.xz.h / g.xy.h, got2 = g.yz.w / g.xy.w;
  if (Math.abs(got - want) > .02 || Math.abs(got2 - (D * vz) / (Wx * vx)) > .02)
    fail(`the side views are not at physical proportions: ${got} vs ${want}`);
  const xyBox = await box("#oXY");
  await send("Input.dispatchMouseEvent",{type:"mousePressed",x:xyBox.x+xyBox.width*.25,y:xyBox.y+xyBox.height*.75,button:"left",clickCount:1});
  await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:xyBox.x+xyBox.width*.25,y:xyBox.y+xyBox.height*.75,button:"left",clickCount:1});
  await sleep(300);
  const cr = JSON.parse(await ev("JSON.stringify({x:V.vol.cx,y:V.vol.cy,z:V.vol.cz})"));
  if (Math.abs(cr.x - Wx * .25) > 3 || Math.abs(cr.y - Hy * .75) > 3) fail("a click in XY did not move the crosshair there: " + JSON.stringify(cr));
  const z0 = cr.z;
  for (let k = 0; k < 5; k++) await send("Input.dispatchMouseEvent",{type:"mouseWheel",x:xyBox.x+20,y:xyBox.y+20,deltaX:0,deltaY:100});
  await sleep(300);
  const z1 = await ev("V.vol.cz");
  if (z1 !== Math.min(D - 1, z0 + 5)) fail(`the wheel in XY did not step the depth: ${z0} -> ${z1}`);
  const xzImg = () => ev("(()=>{const c=document.getElementById('oXZ'),g=c.getContext('2d'),d=g.getImageData(0,0,c.width,c.height).data;let s=0;for(let i=0;i<d.length;i+=40)s+=d[i];return s;})()");
  const slice = await xzImg(); await shot("ortho_slices");
  await click("#oMax"); const proj = await xzImg(); await shot("ortho_max");
  if (!(proj > slice)) fail(`max did not brighten the side view: ${slice} -> ${proj}`);
  await click("#volBtn");                                     // 3D after XYZ: the texture path
  await sleep(600);
  if ((await look()).peak < 100) fail("3D after the XYZ views is black");
  console.log("  ortho       :", JSON.stringify({xz_over_xy: +got.toFixed(3), want: +want.toFixed(3), cross: cr, z_after_wheel: z1, xz_sum: [slice, proj]}));

  // the view saves the 3D state and a reload brings it back
  await sleep(600);
  await send("Page.reload"); await sleep(2600);
  const back = JSON.parse(await ev("JSON.stringify(V.vol)"));
  if (!back.on || back.mode !== "glass" || Math.abs(back.yaw - ang.yaw) > 1e-6) fail("the 3D view was not restored: " + JSON.stringify(back));

  console.log("  stack:", JSON.stringify(meta));
  console.log("  from above  :", JSON.stringify(top));
  console.log("  turned      :", JSON.stringify(turned), JSON.stringify(ang));
  console.log("  depth       :", JSON.stringify(depth));
  console.log("  glass       :", JSON.stringify(glass));
  console.log("  restored    :", back.mode, "yaw", back.yaw.toFixed(2));
  console.log("  console errors:", errors.length, errors.slice(0,2));
  chrome.kill(); process.exit(errors.length ? 1 : 0);
})();
