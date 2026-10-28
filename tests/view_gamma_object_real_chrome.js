/* Gamma per channel and grown objects in 3D, in a real Chrome. Same CDP harness as the other
   real-browser checks, no puppeteer.

     python tools/make_synthetic.py --stack synthetic_stack.mesc
     mesc-io view synthetic_stack.mesc --port 8033 --no-browser &
     node tests/view_gamma_object_real_chrome.js http://127.0.0.1:8033/ <out prefix>

   The synthetic stack's objects are known (tools/make_synthetic.py): axon 1 runs from (20, 30) at
   slice 0 to (100, 90) at slice 47 with a bouton every 12 slices from slice 4; a red cell sits at
   (95, 30), slice 16, a Gaussian of 15000 over 9000 with exp(-r²/40) across and exp(-dz²/12) along
   z. Pixels are 0.5 µm, slices 1 µm apart. */
const { spawn } = require("node:child_process"); const http = require("node:http"); const fs = require("node:fs");
const URL_ = process.argv[2], OUT = process.argv[3] || "/tmp/gamma_object";
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9347;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data",d=>b+=d); r.on("end",()=>res(JSON.parse(b))); }).on("error", rej));
const bouton = bz => [bz, 30 + 60 * bz / 47, 20 + 80 * bz / 47];
(async () => {
  const chrome = spawn(CHROME, ["--headless=new","--remote-debugging-port="+PORT,"--no-first-run",
    "--user-data-dir=/tmp/gamma_object_profile","--window-size=1500,1000","--enable-unsafe-swiftshader",
    "--use-angle=swiftshader","about:blank"], {stdio:"ignore"});
  process.on("exit", () => { try { chrome.kill(); } catch(_){} });
  let t; for (let i=0;i<30;i++){ try { t = await getJSON(`http://127.0.0.1:${PORT}/json`); break; } catch { await sleep(300);} }
  const ws = new WebSocket(t.find(x=>x.type==="page").webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id=0; const pend=new Map(); const errors=[];
  ws.onmessage = m => { const d=JSON.parse(m.data);
    if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); }
    else if (d.method==="Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description||d.params.exceptionDetails.text);
    else if (d.method==="Runtime.consoleAPICalled" && d.params.type==="error") errors.push("console.error: " + d.params.args.map(a => a.value ?? a.description).join(" ")); };
  const send=(m,p={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}));});
  const ev=async e=>{const r=await send("Runtime.evaluate",{expression:e,returnByValue:true,awaitPromise:true});
    if(r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description||r.result.exceptionDetails.text); return r.result.result.value;};
  const J = async e => JSON.parse(await ev(`JSON.stringify(${e})`));
  const fail=m=>{console.error("  FAIL: "+m); chrome.kill(); process.exit(1);};
  const shot = async name => { const s = await send("Page.captureScreenshot",{format:"png"});
    fs.writeFileSync(`${OUT}_${name}.png`, Buffer.from(s.result.data,"base64")); };
  const clickAt = async (x, y, modifiers = 0) => {
    for (const type of ["mouseMoved","mousePressed","mouseReleased"])
      await send("Input.dispatchMouseEvent",{type,x,y,button:"left",clickCount:1,modifiers});
    await sleep(350); };
  const key = async (shift = false) => { const k = {key:"Escape",code:"Escape",windowsVirtualKeyCode:27,modifiers:shift ? 8 : 0};
    await send("Input.dispatchKeyEvent",{type:"keyDown",...k}); await send("Input.dispatchKeyEvent",{type:"keyUp",...k}); await sleep(200); };
  const screenOf = q => J(`(()=>{const c=document.getElementById('vol'), r=c.getBoundingClientRect(), k=volCam(r.width/r.height);
    const p=volProject(volVoxWorld(${JSON.stringify(q)}, k.ext), k, r.width, r.height); return {x:r.left+p[0], y:r.top+p[1]};})()`);
  // every pixel of the GL picture: a hash of all of them, and the sum of r+g+b
  const gl = () => J(`(()=>{const c=document.getElementById('vol'),g=c.getContext('webgl2'),p=new Uint8Array(c.width*c.height*4);
    g.readPixels(0,0,c.width,c.height,g.RGBA,g.UNSIGNED_BYTE,p); let h=0, s=0; for(let i=0;i<p.length;i++){ h=(Math.imul(h,31)+p[i])>>>0; if((i&3)!==3) s+=p[i]; } return {h,s};})()`);
  // ... and of a 2D canvas (an XYZ pane)
  const cv2 = cid => J(`(()=>{const c=document.getElementById('${cid}'),d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
    let h=0, s=0; for(let i=0;i<d.length;i++){ h=(Math.imul(h,31)+d[i])>>>0; if((i&3)!==3) s+=d[i]; } return {h,s};})()`);
  const setGam = (ch, g) => ev(`(()=>{const nb=[...document.querySelectorAll('#volGam .vgam, #oGam .vgam')].find(n=>+n.dataset.ch===${ch} && n.offsetParent);
    if(!nb) return 'none'; nb.value=${g}; nb.onchange(); return 'ok';})()`);
  const settle = async () => { await sleep(300); await ev("volBusy = false; volDraw(); 'ok'"); await sleep(100); };
  const waitStack = async ov => { for (let i = 0; i < 60 && !(await ev(ov ? "!!(volMeta && volMeta.ov && !volLoading)" : "!!(volMeta && !volMeta.ov && volKey.endsWith('|1|100') && !volLoading)")); i++) await sleep(250); await sleep(400); };

  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.navigate",{url:URL_}); await sleep(2200);
  const stack = await ev("FILE.units.findIndex(u => u.z_step_um)");
  if (stack < 0) fail("no z-stack in this file");
  await ev(`pick(${stack}); V.ch = 0; V.overlay = false; V.lo = 1; V.hi = 100; V.vol = volState(null); V.vol.on = true; V.vol.mode = 'mip'; V.proj = '';
    V.frame = 16; $('frame').value = 16; $('frame').oninput(); volShow(); 'ok'`);   // the slice of the cell and a bouton: glass marks it in blue
  await waitStack(false);
  if (!(await ev("!!volMeta"))) fail("the stack never reached the GPU");
  const path = await ev(`FILE.units[${stack}].path`);
  const u = await J(`(()=>{const x=FILE.units[${stack}]; return {px:x.pixel_size_um, py:x.pixel_size_y_um||x.pixel_size_um, dz:x.z_step_um, down:volMeta.down};})()`);

  // ---- 1. gamma ------------------------------------------------------------------------------
  // one number per channel shown, 1 by default; at 1 the picture is the very same pixels
  const gs = await J("[...document.querySelectorAll('#volGam .vgam')].map(n => [n.dataset.ch, +n.value])");
  if (JSON.stringify(gs) !== '[["0",1]]') fail("the 3D bar does not show one gamma for ch0 at 1: " + JSON.stringify(gs));
  const gam = {};
  for (const mode of ["mip", "glass", "depth"]) {
    await ev(`V.vol.mode = '${mode}'; volShow(); 'ok'`); await settle();
    const g1 = await gl();
    await setGam(0, 0.5); await settle(); const gLo = await gl();
    await setGam(0, 2); await settle(); const gHi = await gl();
    if (mode === "mip") await shot("gamma_mip_2");
    await setGam(0, 1); await settle(); const gBack = await gl();
    if (gBack.h !== g1.h) fail(`${mode}: gamma back at 1 is not the same picture to the bit: ${g1.h} vs ${gBack.h}`);
    // (glass, looking down, is mostly the current slice's blue sheet, held at a quarter of white: it moves
    // less — and since 0.4.1 the floor no longer stretches the brightness, so more of glass sits at white)
    const by = mode === "glass" ? 1.002 : 1.02;
    if (!(gLo.s > g1.s * by && g1.s > gHi.s * by)) fail(`${mode}: gamma is not monotonic (0.5 brighter, 2 darker): ${JSON.stringify([gLo.s, g1.s, gHi.s])}`);
    gam[mode] = { "0.5": gLo.s, "1": g1.s, "2": gHi.s, identical_at_1: true };
  }
  await ev("V.vol.mode = 'mip'; volShow(); 'ok'"); await settle();
  // the PNG is the picture with gamma, and its caption says so
  // the PNG is handed to a stand-in for withCaption, which sums its pixels and keeps its caption (again after a reload)
  const hookPng = () => ev(`window.__png = null; if (!window.__wc0) { window.__wc0 = withCaption; withCaption = (src, lines) => { const d=src.getContext('2d').getImageData(0,0,src.width,src.height).data; let s=0; for(let i=0;i<d.length;i+=4) s+=d[i]+d[i+1]+d[i+2]; window.__png = {s, lines}; }; } 'ok'`);
  await hookPng();
  await ev("exportVolPng(); 'ok'"); const png1 = await J("window.__png");
  await setGam(0, 0.5); await ev("exportVolPng(); 'ok'"); const png05 = await J("window.__png");
  if (!(png05.s > png1.s * 1.02) || png1.lines.some(l => l.startsWith("gamma")) || !png05.lines.includes("gamma ch0 0.5")) fail("the 3D PNG does not carry gamma: " + JSON.stringify([png1, png05]));
  if (!(await ev("document.getElementById('volInfo').textContent")).includes("gamma ch0 0.5")) fail("the 3D info does not say gamma is on");
  await setGam(0, 1); await settle();
  // the XYZ panes: the bytes through gamma, and at 1 the same pixels
  await ev("V.vol.on = false; V.vol.ortho = true; V.vol.oMax = true; volShow(); orthoDraw(); 'ok'"); await sleep(400);
  if (!(await ev("!!document.querySelector('#oGam .vgam')"))) fail("no gamma over the XYZ views");
  const o1 = await cv2("oXY"); await setGam(0, 0.5); await sleep(200); const o05 = await cv2("oXY");
  await shot("gamma_xyz_05");
  await setGam(0, 2); await sleep(200); const o2 = await cv2("oXY");
  await setGam(0, 1); await sleep(200); const oB = await cv2("oXY");
  if (oB.h !== o1.h) fail("XYZ: gamma back at 1 is not the same pane to the bit");
  if (!(o05.s > o1.s * 1.02 && o1.s > o2.s * 1.02)) fail("XYZ: gamma is not monotonic: " + JSON.stringify([o05.s, o1.s, o2.s]));
  gam.xyz = { "0.5": o05.s, "1": o1.s, "2": o2.s };
  // two channels: each its own gamma; red's leaves the green alone
  await ev("V.overlay = true; volShow(); 'ok'"); await waitStack(true); await ev("orthoDraw(); 'ok'"); await sleep(200);
  const ogs = await J("[...document.querySelectorAll('#oGam .vgam')].map(n => n.dataset.ch)");
  if (JSON.stringify(ogs) !== '["0","1"]') fail("the overlay does not give each channel its gamma: " + JSON.stringify(ogs));
  const greenOf = cid => J(`(()=>{const c=document.getElementById('${cid}'),d=c.getContext('2d').getImageData(0,0,c.width,c.height).data; let r=0,g=0; for(let i=0;i<d.length;i+=4){r+=d[i]; g+=d[i+1];} return {r,g};})()`);
  const ov1 = await cv2("oXY"), ovc1 = await greenOf("oXY");
  await setGam(1, 0.5); await sleep(200); const ovc05 = await greenOf("oXY");
  await setGam(1, 1); await sleep(200); const ovB = await cv2("oXY");
  if (ovB.h !== ov1.h) fail("XYZ overlay: gamma back at 1 is not the same pane to the bit");
  if (!(ovc05.r > ovc1.r * 1.02)) fail("XYZ overlay: red's gamma did not brighten red: " + JSON.stringify([ovc1, ovc05]));
  await ev("V.vol.ortho = false; V.vol.on = true; volShow(); 'ok'"); await settle();
  const v1 = await gl(); await setGam(1, 0.5); await settle(); const v05 = await gl(); await setGam(1, 1); await settle(); const vB = await gl();
  if (vB.h !== v1.h || !(v05.s > v1.s * 1.02)) fail("3D overlay: red's gamma is not identical at 1 or not brighter at 0.5: " + JSON.stringify([v1, v05, vB]));
  gam.overlay = { xyz_red: [ovc1.r, ovc05.r], gl: [v1.s, v05.s] };
  // saved with the view
  await setGam(0, 0.7); await ev("saveView(); 'ok'"); await sleep(700);
  await send("Page.reload"); await sleep(2600); await waitStack(true);
  if (await ev("V.vol.gam[0]") !== 0.7 || await ev("+document.querySelector('#volGam .vgam').value") !== 0.7) fail("gamma did not come back with the view");
  if (await ev("volState({gam: [null, 'x', 9, -1]}).gam.slice(0, 4).join()") !== "1,1,3,0.3") fail("volState does not validate gamma");
  await setGam(0, 1);
  console.log("  gamma       :", JSON.stringify(gam));

  // ---- 2. objects ----------------------------------------------------------------------------
  // the red cell, in the overlay: grown in red, centred on the cell
  await ev("V.vol.mode = 'mip'; volReset(); 'ok'"); await settle();
  await ev("$('volObject').click(); 'ok'");
  if (await ev("V.vol.tool") !== "object") fail("the object button did not switch the tool on");
  if (await ev("document.getElementById('volObjL').hidden") || await ev("+$('volObjF').value") !== 50 || await ev("+$('volObjR').value") !== 15) fail("the object's share and radius are not shown at 50 % and 15 µm");
  const cell = [16, 30, 95], sc = await screenOf(cell);
  await clickAt(sc.x, sc.y);
  let O = await J("volObjs()");
  if (O.length !== 1 || O[0].ch !== 1 || O[0].frac !== .5 || O[0].r !== 15) fail("a click did not add one object grown in red: " + JSON.stringify(O));
  // the region is grown by the server on the recording's values: wait for its answer
  const region = async n => { for (let i = 0; i < 80; i++) { const r = await J(`(()=>{const o=volObjs()[${n}], r=o && volObjRegion(o); return r ? {...volObjStats(r), cen:r.centre_vox, capR:r.reached_radius, capN:r.stopped_at_max, peak:r.peak} : null;})()`);
    if (r) return r; await sleep(150); } fail("no answer from the server for object " + n); };
  const st = await region(0);
  const k = u.down, cenFull = st.cen;
  if (!(Math.abs(cenFull[0] - 16) <= 1.5 && Math.abs(cenFull[1] - 30) <= 1.5 && Math.abs(cenFull[2] - 95) <= 1.5)) fail("the cell's object is not centred on (95, 30, 16): " + JSON.stringify(cenFull));
  // half way from the red background to the peak, on the recording's values: an ellipsoid ~2.6 µm across, ~2.9 µm along z
  if (!(st.um3 > 40 && st.um3 < 170) || st.capR || st.capN) fail("the cell's volume is not plausible (or a cap stopped it): " + JSON.stringify(st));
  if (Math.abs(st.um3 - st.n * u.px * u.py * u.dz) > 1e-6) fail("the volume is not voxels × voxel size (full resolution)");
  const red = st.means.find(m => m.ch === 1).v, green = st.means.find(m => m.ch === 0).v;
  // in reader units (raw × 0.5 − 786): red's background 3714, the cell's peak 11214, so a region kept half way
  // up averages well above 7000; green is its background, -336, there
  if (!(red > 7000 && red < 11300 && green < 0)) fail("the object's means are not the cell's red and the background's green: " + JSON.stringify(st.means));
  const lst = await ev("document.getElementById('volPts').textContent");
  if (!lst.includes("o1") || !lst.includes("µm³") || !/mean ch0 ≈ -?[\d.]+ · ch1 ≈ -?[\d.]+/.test(lst) || !lst.includes(`slice ${st.slice}`)) fail("the list does not give the object: " + lst);
  await sleep(200); const cross = await J("({cx:V.vol.cx, cy:V.vol.cy, z:V.frame})");
  if (Math.abs(cross.cx - 95 / k) > 2 || Math.abs(cross.cy - 30 / k) > 2 || Math.abs(cross.z - 16) > 1) fail("the crosshair did not go to the object's centre: " + JSON.stringify(cross));
  const teal = (cid, cx = null, cy = null, R = 20) => ev(`(()=>{const c=document.getElementById('${cid}'), g=c.getContext('2d'), r=c.getBoundingClientRect(), s=c.width/r.width;
    const x0=${cx === null ? 0 : `Math.max(0,Math.round((${cx}-r.left)*s)-${R})`}, y0=${cy === null ? 0 : `Math.max(0,Math.round((${cy}-r.top)*s)-${R})`};
    const w=${cx === null ? "c.width" : `Math.min(c.width-x0,${2 * R})`}, h=${cy === null ? "c.height" : `Math.min(c.height-y0,${2 * R})`};
    const d=g.getImageData(x0,y0,w,h).data; let n=0; for(let i=0;i<d.length;i+=4) if(d[i]<120&&d[i+1]>180&&d[i+2]>150&&d[i+3]>100) n++; return n;})()`);
  const cen3 = await screenOf(cenFull), mk3 = await teal("volMarks", cen3.x, cen3.y);
  if (mk3 < 15) fail("no object marker at the centre in 3D: " + mk3);
  await shot("object_cell_3d");
  // the bouton at slice 16 of axon 1, in green alone: small, and it stays a bouton
  await ev("V.overlay = false; volShow(); 'ok'"); await waitStack(false); await settle();
  const b16 = bouton(16), s16 = await screenOf(b16.map(Math.round));
  await clickAt(s16.x, s16.y);
  O = await J("volObjs()");
  if (O.length !== 2 || O[1].ch !== 0) fail("the bouton's object is not grown in ch0: " + JSON.stringify(O));
  // the furthest of an object's voxels (on the page's grid, each block's centre) from its peak, in µm, and its size
  const far = async n => { await region(n); return J(`(()=>{const r=volObjRegion(volObjs()[${n}]), [D,H,W]=volMeta.shape, S=H*W, k=volMeta.down;
    const vx=unit.pixel_size_um, vy=unit.pixel_size_y_um||vx, vz=unit.z_step_um, p=r.peak_vox; let m=0;
    for(const i of r.idx){const z=Math.floor(i/S), y=Math.floor((i-z*S)/W), x=i-z*S-y*W; m=Math.max(m, Math.hypot(((x+.5)*k-.5-p[2])*vx,((y+.5)*k-.5-p[1])*vy,(z-p[0])*vz));}
    return {far:m, n:r.n, capR:r.reached_radius, cen:r.centre_vox, um3:r.um3};})()`); };
  const blockHalf = (u.down - 1) / 2 * Math.hypot(u.px, u.py);   // a block's centre is that far from its furthest voxel
  const bo = await far(1);
  if (Math.abs(bo.cen[0] - b16[0]) > 1.5 || Math.abs(bo.cen[1] - b16[1]) > 2 || Math.abs(bo.cen[2] - b16[2]) > 2) fail("the bouton's object is not centred on it: " + JSON.stringify([bo.cen, b16]));
  if (bo.capR || bo.far > 6) fail("at half its peak the bouton's object ran along the axon: " + JSON.stringify(bo));
  // a low share (10 %) takes the axon in too: with a 3 µm radius it stops there; with 15 µm it runs further
  await ev("$('volObjF').value = 10; $('volObjF').onchange(); $('volObjR').value = 3; $('volObjR').onchange(); 'ok'");
  const lo3 = await far(1);
  await ev("$('volObjR').value = 15; $('volObjR').onchange(); 'ok'");
  const lo15 = await far(1);
  if (lo3.far > 3 + blockHalf + 1e-9 || !lo3.capR) fail("the radius did not hold the object at 3 µm: " + JSON.stringify(lo3));
  if (!(lo15.far > 6 && lo15.n > 2 * lo3.n)) fail("the positive control failed: at 10 % without a tight radius the object should run along the axon: " + JSON.stringify(lo15));
  if (lo15.far > 15 + blockHalf + 1e-9) fail("the object went past its 15 µm radius: " + JSON.stringify(lo15));
  await shot("object_bouton_leak15");
  await ev("$('volObjF').value = 50; $('volObjF').onchange(); 'ok'");
  const bo2 = await far(1);
  if (bo2.n !== bo.n) fail("back at 50 % and 15 µm the bouton's object is not what it was: " + JSON.stringify([bo, bo2]));
  // in XYZ: the regions drawn in their panes
  await ev("V.vol.on = false; V.vol.ortho = true; V.vol.oMax = false; volGoTo(volObjCentre(volObjRegion(volObjs()[1])).q); volShow(); orthoDraw(); 'ok'"); await sleep(400);
  const xyT = await teal("oXY"), yzT = await teal("oYZ");
  await shot("object_xyz");
  if (xyT < 10 || yzT < 10) fail("the bouton's object is not drawn in XY and YZ: " + JSON.stringify([xyT, yzT]));
  await ev("V.vol.oMax = true; orthoDraw(); 'ok'"); await sleep(200);
  const maxT = await teal("oXY");
  await ev("V.vol.oMax = false; V.vol.ortho = false; V.vol.on = true; volShow(); 'ok'"); await settle();
  if (maxT <= xyT) fail("in the projection both objects are not drawn: " + JSON.stringify([xyT, maxT]));
  // grown on the server, the red cell's object keeps its numbers while only green is on the page
  if (!/o1\s+[\d.]+ µm³/.test(await ev("document.getElementById('volPts').textContent"))) fail("the red object's numbers are not listed while green alone is shown");
  // the PNG caption lists what it can grow
  await hookPng(); await ev("exportVolPng(); 'ok'"); const pngO = await J("window.__png");
  if (!pngO.lines.some(l => l.startsWith("o2: "))) fail("the 3D PNG's caption does not carry the objects: " + JSON.stringify(pngO.lines));
  // saved with the view: seed and numbers, regrown on load to the same region
  await ev("V.overlay = true; volShow(); 'ok'"); await waitStack(true); await settle();
  await region(0); await region(1);
  const before = await J("volObjs().map(o => ({o, n: volObjRegion(o).n}))");
  await ev("saveView(); 'ok'"); await sleep(700);
  const saved = JSON.parse(await ev(`(async()=>{const r=await fetch('/api/view'); return JSON.stringify((await r.json()).view.vol.objs[${JSON.stringify(path)}] || null);})()`));
  if (!saved || saved.length !== 2 || saved.some(o => "idx" in o || Object.keys(o).sort().join() !== "ch,frac,q,r")) fail("the saved view does not hold just the seed and the numbers: " + JSON.stringify(saved));
  await send("Page.reload"); await sleep(2600); await waitStack(true);
  await region(0); await region(1);
  const after = await J("volObjs().map(o => ({o, n: volObjRegion(o).n}))");
  if (JSON.stringify(after) !== JSON.stringify(before)) fail("the objects did not come back as they were: " + JSON.stringify([before, after]));
  if (await ev("V.vol.tool") !== "object") fail("the object tool was not restored with the view");
  // Esc removes the last, shift+Esc all
  await key(false);
  if ((await J("volObjs()")).length !== 1) fail("Esc did not remove the last object");
  await key(true);
  if ((await J("volObjs()")).length !== 0) fail("shift+Esc did not remove every object");
  if (await ev("Object.keys(volState({objs: {a: [{q:[1,2,3], ch:0}, {q:[1,2], ch:0}, {q:[1,2,3], ch:-1}, 5]}}).objs.a[0]).sort().join()") !== "ch,frac,q,r"
      || await ev("volState({objs: {a: [{q:[1,2], ch:0}]}}).objs.a") !== undefined) fail("volState does not validate the objects");
  console.log("  object      :", JSON.stringify({ cell: { centre: cenFull.map(v => +v.toFixed(2)), um3: +st.um3.toFixed(1), n: st.n, ext: st.ext.map(v => +v.toFixed(1)), red, green, marker_px: mk3 },
                                                    bouton: { centre: bo.cen.map(v => +v.toFixed(2)), um3: +bo.um3.toFixed(1), far: +bo.far.toFixed(2) },
                                                    leak10pct: { r3: { far: +lo3.far.toFixed(2), n: lo3.n, capR: lo3.capR }, r15: { far: +lo15.far.toFixed(2), n: lo15.n, capR: lo15.capR } },
                                                    xyz_teal: [xyT, yzT, maxT] }));

  await ev("if (window.__wc0) withCaption = window.__wc0; V.overlay = false; V.lo = 1; V.hi = 99.5; V.vol = volState(null); saveView(); 'ok'"); await sleep(700);
  console.log("  stack: down", u.down, "· console errors:", errors.length, errors.slice(0,2));
  chrome.kill(); process.exit(errors.length ? 1 : 0);
})();
