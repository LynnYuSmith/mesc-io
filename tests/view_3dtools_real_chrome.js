/* The 3D tools on a z-stack, in a real Chrome: a click picks the bright voxel under the cursor
   and marks it, wherever the stack is turned or flipped. Same CDP harness as the other
   real-browser checks, no puppeteer.

     python tools/make_synthetic.py --stack synthetic_stack.mesc
     mesc-io view synthetic_stack.mesc --port 8032 --no-browser &
     node tests/view_3dtools_real_chrome.js http://127.0.0.1:8032/ <out prefix>

   The synthetic stack's objects are known (tools/make_synthetic.py): axon 1 runs from (20, 30) at
   slice 0 to (100, 90) at slice 47 with a bouton every 12 slices from slice 4; a red cell sits at
   (95, 30), slice 16. Pixels are 0.5 µm, slices 1 µm apart. */
const { spawn } = require("node:child_process"); const http = require("node:http"); const fs = require("node:fs");
const URL_ = process.argv[2], OUT = process.argv[3] || "/tmp/3dtools";
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9343;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data",d=>b+=d); r.on("end",()=>res(JSON.parse(b))); }).on("error", rej));
// a bouton of axon 1 at slice bz, where make_synthetic.py puts it: (z, y, x), sub-pixel
const bouton = bz => [bz, 30 + 60 * bz / 47, 20 + 80 * bz / 47];
(async () => {
  const chrome = spawn(CHROME, ["--headless=new","--remote-debugging-port="+PORT,"--no-first-run",
    "--user-data-dir=/tmp/3dtools_profile","--window-size=1500,1000","--enable-unsafe-swiftshader",
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
  const J = async e => JSON.parse(await ev(`JSON.stringify(${e})`));
  const fail=m=>{console.error("  FAIL: "+m); chrome.kill(); process.exit(1);};
  const shot = async name => { const s = await send("Page.captureScreenshot",{format:"png"});
    fs.writeFileSync(`${OUT}_${name}.png`, Buffer.from(s.result.data,"base64")); };
  const clickAt = async (x, y, modifiers = 0) => {
    for (const type of ["mouseMoved","mousePressed","mouseReleased"])
      await send("Input.dispatchMouseEvent",{type,x,y,button:"left",clickCount:1,modifiers});
    await sleep(350); };
  // where a full-resolution voxel (z, y, x) is on screen, through the page's own camera and flags
  const screenOf = q => J(`(()=>{const c=document.getElementById('vol'), r=c.getBoundingClientRect(), k=volCam(r.width/r.height);
    const p=volProject(volVoxWorld(${JSON.stringify(q)}, k.ext), k, r.width, r.height); return {x:r.left+p[0], y:r.top+p[1]};})()`);
  // the brightest voxel of channel j's bytes within ±rz slices and ±rxy pixels of a point
  const brightestNear = (q, j = 0, rz = 2, rxy = 3) => J(`(()=>{const [D,H,W]=volMeta.shape, a=volBytes[${j}], q=${JSON.stringify(q)};
    let b=-1, at=null; for(let z=Math.max(0,Math.round(q[0])-${rz}); z<=Math.min(D-1,Math.round(q[0])+${rz}); z++)
    for(let y=Math.max(0,Math.round(q[1])-${rxy}); y<=Math.min(H-1,Math.round(q[1])+${rxy}); y++)
    for(let x=Math.max(0,Math.round(q[2])-${rxy}); x<=Math.min(W-1,Math.round(q[2])+${rxy}); x++){const v=a[(z*H+y)*W+x]; if(v>b){b=v; at=[z,y,x];}}
    return at;})()`);
  const near = (a, b, tz, txy) => Math.abs(a[0] - b[0]) <= tz && Math.abs(a[1] - b[1]) <= txy && Math.abs(a[2] - b[2]) <= txy;
  const pts = () => J("volPts()");
  // orange marker pixels in a canvas (2D), in a box around a point given in that canvas's CSS pixels
  const orangeIn = (cid, cx = null, cy = null, R = 30) => ev(`(()=>{const c=document.getElementById('${cid}'), g=c.getContext('2d'), r=c.getBoundingClientRect(), s=c.width/r.width;
    const x0=${cx === null ? 0 : `Math.max(0,Math.round((${cx}-r.left)*s)-${R})`}, y0=${cy === null ? 0 : `Math.max(0,Math.round((${cy}-r.top)*s)-${R})`};
    const w=${cx === null ? "c.width" : `Math.min(c.width-x0,${2 * R})`}, h=${cy === null ? "c.height" : `Math.min(c.height-y0,${2 * R})`};
    const d=g.getImageData(x0,y0,w,h).data; let n=0; for(let i=0;i<d.length;i+=4) if(d[i]>200&&d[i+1]>120&&d[i+1]<200&&d[i+2]<90&&d[i+3]>100) n++; return n;})()`);

  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.navigate",{url:URL_}); await sleep(2200);
  const stack = await ev("FILE.units.findIndex(u => u.z_step_um)");
  if (stack < 0) fail("no z-stack in this file");
  // a clean start, the whole range in the window (no voxel held at 255, so the brightest is one voxel)
  await ev(`pick(${stack}); V.overlay = false; V.lo = 1; V.hi = 100; V.vol = volState(null); V.vol.on = true; V.vol.mode = 'mip'; volShow(); 'ok'`);
  for (let i = 0; i < 40 && !(await ev("!!(volMeta && volKey.endsWith('|1|100'))")); i++) await sleep(250);
  if (!(await ev("!!volMeta"))) fail("the stack never reached the GPU");
  await sleep(500);
  const meta = await J("volMeta");
  const u = await J(`(()=>{const x=FILE.units[${stack}]; return {px:x.pixel_size_um, py:x.pixel_size_y_um||x.pixel_size_um, dz:x.z_step_um};})()`);

  // ---- 1. point: a click on a bouton marks its brightest voxel --------------------------------
  const pic0 = await ev("(()=>{const c=document.getElementById('vol'),g=c.getContext('webgl2'),p=new Uint8Array(c.width*c.height*4);g.readPixels(0,0,c.width,c.height,g.RGBA,g.UNSIGNED_BYTE,p);let s=0;for(let i=0;i<p.length;i+=4*89)s=(s*31+p[i])>>>0;return s;})()");
  await ev("$('volPoint').click(); 'ok'");
  if (await ev("V.vol.tool") !== "point") fail("the point button did not switch the tool on");
  const pic1 = await ev("(()=>{const c=document.getElementById('vol'),g=c.getContext('webgl2'),p=new Uint8Array(c.width*c.height*4);g.readPixels(0,0,c.width,c.height,g.RGBA,g.UNSIGNED_BYTE,p);let s=0;for(let i=0;i<p.length;i+=4*89)s=(s*31+p[i])>>>0;return s;})()");
  if (pic0 !== pic1) fail("switching the point tool on changed the 3D picture");
  const b16 = bouton(16), want16 = await brightestNear(b16);
  const s16 = await screenOf(b16.map(Math.round));
  await clickAt(s16.x, s16.y);
  let P = await pts();
  if (P.length !== 1) fail("a click with the point tool did not add one point: " + JSON.stringify(P));
  const p1 = P[0];
  if (!near(p1, b16, 1, 1.5)) fail(`the point is not on the bouton at ${b16.map(v => v.toFixed(1))}: ${p1}`);
  if (!near(p1, want16, 1, 1)) fail(`the point is not the bouton's brightest voxel ${want16}: ${p1}`);
  if (await ev("V.vol.yaw") !== 0) fail("a click turned the stack");
  const cross = await J("({cx:V.vol.cx, cy:V.vol.cy, z:V.frame})");
  if (cross.cx !== p1[2] || cross.cy !== p1[1] || cross.z !== p1[0]) fail("the XYZ crosshair did not move to the point: " + JSON.stringify(cross));
  const list = await ev("document.getElementById('volPts').textContent");
  const um = [p1[2] * u.px, p1[1] * u.py, p1[0] * u.dz];
  if (await ev("document.getElementById('volPts').hidden")) fail("the point list is not shown");
  if (!list.includes(`x ${um[0].toFixed(2)} · y ${um[1].toFixed(2)} · z ${um[2].toFixed(1)}`) || !list.includes(`slice ${p1[0]}`) || !/ch0 ≈ \d/.test(list))
    fail("the point list does not give the point's µm, slice and value: " + list);
  const mk = await orangeIn("volMarks", s16.x, s16.y);
  if (mk < 20) fail("no marker drawn at the point: " + mk);
  await shot("point_top");
  // a drag with the tool on still turns, and adds nothing
  const b = JSON.parse(await ev("JSON.stringify(document.getElementById('vol').getBoundingClientRect())")), cx = b.x + b.width / 2, cy = b.y + b.height / 2;
  await send("Input.dispatchMouseEvent",{type:"mousePressed",x:cx,y:cy,button:"left",clickCount:1});
  for (let k = 1; k <= 8; k++) await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:cx+k*10,y:cy+k*6,button:"left"});
  await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:cx+80,y:cy+48,button:"left",clickCount:1});
  await sleep(400);
  if (Math.abs(await ev("V.vol.yaw")) < .5) fail("a drag with the point tool on did not turn the stack");
  if ((await pts()).length !== 1) fail("a drag added a point");
  // turned: the marker follows the voxel (it is on the bright bouton), and a click there picks the same voxel
  const s16t = await screenOf(p1);
  if (await orangeIn("volMarks", s16t.x, s16t.y, 14) < 10) fail("the marker did not follow the turn");
  await clickAt(s16t.x, s16t.y);
  P = await pts();
  if (P.length !== 2 || !near(P[1], p1, 1, 1)) fail("a click on the marked bouton, turned, did not pick it again: " + JSON.stringify(P));
  await shot("point_turned");
  // flipped (MESc rows) and deepest-up: the stored voxel does not change, the marker moves with the picture
  await ev("$('flipBtn').click(); $('volDeep').click(); 'ok'"); await sleep(400);
  const P2 = await pts();
  if (JSON.stringify(P2) !== JSON.stringify(P)) fail("flipping changed the stored points: " + JSON.stringify([P, P2]));
  const s16f = await screenOf(p1);
  await clickAt(s16f.x, s16f.y);
  P = await pts();
  if (P.length !== 3 || !near(P[2], p1, 1, 1)) fail("under flip + deepest-up a click on the bouton did not pick it: " + JSON.stringify(P));
  await ev("$('flipBtn').click(); $('volDeep').click(); volReset(); 'ok'"); await sleep(300);
  // a second bouton, slice 40
  const b40 = bouton(40), s40 = await screenOf(b40.map(Math.round));
  await clickAt(s40.x, s40.y);
  P = await pts();
  if (P.length !== 4 || !near(P[3], b40, 1, 1.5)) fail("the bouton at slice 40 was not picked: " + JSON.stringify(P[3]));
  const p40 = P[3];
  // Esc removes the last; the list follows
  await send("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27}); await send("Input.dispatchKeyEvent",{type:"keyUp",key:"Escape",code:"Escape",windowsVirtualKeyCode:27}); await sleep(200);
  if ((await pts()).length !== 3) fail("Esc did not remove the last point");
  // in XYZ: the crosshair at the last pick, the points drawn in the pane that passes through them
  await ev("V.vol.on = false; V.vol.ortho = true; V.vol.oMax = false; volGoTo(volPts()[0]); volShow(); 'ok'"); await sleep(500);
  const xyMarks = await orangeIn("oXY"); await shot("point_xyz");
  if (xyMarks < 10) fail("the point is not drawn in the XY view: " + xyMarks);
  await ev("V.vol.ortho = false; V.vol.on = true; volShow(); volDraw(); 'ok'"); await sleep(500);
  // the PNG has the markers
  await ev("window.__png=null; window.__savePng0 = savePng; savePng=(c,n)=>{ const g=c.getContext('2d'), d=g.getImageData(0,0,c.width,c.height).data; let o=0; for(let i=0;i<d.length;i+=4) if(d[i]>200&&d[i+1]>120&&d[i+1]<200&&d[i+2]<90) o++; window.__png={w:c.width,h:c.height,name:n,orange:o}; }; 'ok'");
  await ev("exportVolPng(); 'ok'"); await sleep(300);
  const png1 = await J("window.__png");
  if (!png1 || png1.orange < 30) fail("the 3D PNG has no point markers: " + JSON.stringify(png1));
  // coarse while moving: the marker layer follows the GL canvas's size, then back at rest
  const sizes = await J("(()=>{volInteract(); volDraw(); const a=[$('vol').width,$('volMarks').width,volBusy]; return a;})()");
  if (!sizes[2] || sizes[0] !== sizes[1]) fail("while moving the marker layer is not the GL canvas's size: " + sizes);
  await sleep(400);
  // the points are saved with the view, per unit, and come back after a reload
  await ev("saveView(); 'ok'"); await sleep(700);
  await send("Page.reload"); await sleep(2800);
  const back = await J(`V.vol.pts[FILE.units[${stack}].path] || []`);
  if (back.length !== 3 || JSON.stringify(back[0]) !== JSON.stringify(p1)) fail("the points did not come back with the view: " + JSON.stringify(back));
  // shift+Esc clears them all
  for (let i = 0; i < 40 && !(await ev("!!volMeta")); i++) await sleep(250);
  await send("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27,modifiers:8}); await send("Input.dispatchKeyEvent",{type:"keyUp",key:"Escape",code:"Escape",windowsVirtualKeyCode:27,modifiers:8}); await sleep(200);
  if ((await pts()).length !== 0) fail("shift+Esc did not clear every point");
  // two channels: a click on the red cell (95, 30, slice 16) away from the axons picks it, and the
  // list gives both channels' values, red far above green
  // (the whole range again: in a window that holds the cell's core at 255, the brightest along the
  // ray is the first saturated voxel, the near face of the blob — true, but not the centre to test)
  await ev("V.overlay = true; V.lo = 1; V.hi = 100; volShow(); volReset(); 'ok'");
  for (let i = 0; i < 40 && !(await ev("!!(volMeta && volMeta.ov)")); i++) await sleep(250);
  await sleep(500);
  if (await ev("V.vol.tool") !== "point") fail("the tool was not restored with the view");
  const cell = [16, 30, 95], sc = await screenOf(cell);
  await clickAt(sc.x, sc.y);
  P = await pts();
  if (P.length !== 1 || !near(P[0], cell, 3, 2)) fail("the red cell was not picked in the overlay: " + JSON.stringify(P));
  const list2 = await ev("document.getElementById('volPts').textContent");
  const vals = [...list2.matchAll(/ch(\d) [≈≤≥] ([\d.e+-]+)/g)].map(m => [+m[1], +m[2]]);
  if (vals.length !== 2 || !(vals[1][1] > 3 * vals[0][1])) fail("the overlay point does not list both channels (red above green): " + list2);
  await shot("point_overlay");
  console.log("  point       :", JSON.stringify({ bouton16: b16.map(v => +v.toFixed(2)), brightest: want16, picked: p1, um, bouton40: p40,
                                                    marker_px: mk, xy_marks: xyMarks, png_orange: png1.orange, coarse: sizes, overlay_cell: P[0], values: vals }));
  await send("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27,modifiers:8}); await send("Input.dispatchKeyEvent",{type:"keyUp",key:"Escape",code:"Escape",windowsVirtualKeyCode:27,modifiers:8});
  await ev("V.overlay = false; V.lo = 1; V.hi = 99.5; V.vol = volState(null); saveView(); 'ok'"); await sleep(700);

  console.log("  stack:", JSON.stringify(meta.shape), "vox", JSON.stringify(meta.vox), "down", meta.down);
  console.log("  console errors:", errors.length, errors.slice(0,2));
  chrome.kill(); process.exit(errors.length ? 1 : 0);
})();
