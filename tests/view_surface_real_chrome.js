/* The surface of the tissue in the XYZ panes, in a real Chrome: marks clicked where the tissue
   begins, a surface fitted through them (flat, a tilted plane, a curved one), depth below it for
   the crosshair and every 3D point, the tissue side by brightness or by hand, a CSV, and the marks
   kept with the view across a reload. Same CDP harness as the other real-browser checks.

     python tools/make_synthetic.py --stack synthetic_stack.mesc
     mesc-io view synthetic_stack.mesc --port 8033 --no-browser &
     node tests/view_surface_real_chrome.js http://127.0.0.1:8033/ <out prefix>

   The synthetic stack: 48 slices 1 µm apart, 128×128 pixels of 0.5 µm. The fits are checked on
   marks placed on a known plane and a known paraboloid, exactly representable in whole slices. */
const { spawn } = require("node:child_process"); const http = require("node:http"); const fs = require("node:fs");
const URL_ = process.argv[2], OUT = process.argv[3] || "/tmp/surface";
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9347;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data",d=>b+=d); r.on("end",()=>res(JSON.parse(b))); }).on("error", rej));
// a bouton of axon 1 at slice bz, where make_synthetic.py puts it: (z, y, x), sub-pixel
const bouton = bz => [bz, 30 + 60 * bz / 47, 20 + 80 * bz / 47];
(async () => {
  const chrome = spawn(CHROME, ["--headless=new","--remote-debugging-port="+PORT,"--no-first-run",
    "--user-data-dir=/tmp/surface_profile","--window-size=1500,1000","--enable-unsafe-swiftshader",
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

  const open = async () => {
    await send("Page.navigate",{url:URL_}); await sleep(2200);
    const stack = await ev("FILE.units.findIndex(u => u.z_step_um)");
    if (stack < 0) fail("no z-stack in this file");
    return stack;
  };
  const stack = await open();
  await ev(`pick(${stack}); V.overlay = false; V.lo = 1; V.hi = 100; V.vol = volState(null); V.vol.ortho = true; volShow(); 'ok'`);
  for (let i = 0; i < 40 && !(await ev("!!(volMeta && oGeom)")); i++) { await sleep(250); await ev("orthoDraw(); 'ok'"); }
  if (!(await ev("!!oGeom"))) fail("the XYZ panes never drew");
  const k = await ev("volMeta.down");
  if (await ev("$('oSurfTis').hidden") !== true) fail("the tissue button shows before there is a surface");

  // ---- 1. clicks: the tool on, three clicks in XZ make three marks at the clicked voxels -----------
  await ev("$('oSurf').click(); 'ok'");
  if (!(await ev("V.vol.oSurf"))) fail("the surface button did not switch the tool on");
  if (await ev("$('oSurfInfo').hidden")) fail("no hint when the tool comes on");
  const cross0 = await J("({cx:V.vol.cx, cy:V.vol.cy, z:V.frame})");
  const paneAt = (axis, fx, fy) => J(`(()=>{const r=oGeom.${axis}, s=$('stage').getBoundingClientRect(); return {x:s.left+r.x+${fx}*r.w, y:s.top+r.y+${fy}*r.h};})()`);
  const D = await ev("oGeom.D"), Wx = await ev("oGeom.Wx"), Hy = await ev("oGeom.Hy");
  const want = [];
  const mid = (f, n) => (Math.floor(f * n) + .5) / n;   // a voxel's centre, so a click never lands on an edge
  for (const [fx, fz] of [[.2, .3], [.5, .35], [.8, .4]]) {
    const p = await paneAt("xz", mid(fx, Wx), mid(fz, D)); await clickAt(p.x, p.y);
    want.push([Math.floor(fz * D), Math.min(Hy * k - 1, Math.floor((cross0.cy + .5) * k)), Math.min(Wx * k - 1, Math.floor((Math.floor(fx * Wx) + .5) * k))]);
  }
  let M = await J("surfMarks()");
  if (JSON.stringify(M) !== JSON.stringify(want)) fail("the marks are not the clicked voxels: " + JSON.stringify([M, want]));
  const cross1 = await J("({cx:V.vol.cx, cy:V.vol.cy, z:V.frame})");
  if (JSON.stringify(cross0) !== JSON.stringify(cross1)) fail("a surface click moved the crosshair");
  if ((await ev("surfFit().kind")) !== "plane") fail("three marks are not a plane");
  const cyan = await ev(`(()=>{const c=$('oXZ'), d=c.getContext('2d').getImageData(0,0,c.width,c.height).data; let n=0;
    for(let i=0;i<d.length;i+=4) if(d[i]<140&&d[i+1]>190&&d[i+2]>190) n++; return n;})()`);
  if (cyan < 50) fail("the fitted surface is not drawn in XZ: " + cyan);
  if (await ev("$('oSurfTis').hidden")) fail("the tissue button is hidden with marks");
  await shot("three");
  // shift+click near the middle mark removes it; Esc the last; shift+Esc all
  { const p = await paneAt("xz", mid(.5, Wx), mid(.35, D)); await clickAt(p.x + 2, p.y + 1, 8); }
  M = await J("surfMarks()");
  if (JSON.stringify(M) !== JSON.stringify([want[0], want[2]])) fail("shift+click did not remove the nearest mark: " + JSON.stringify(M));
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }); await sleep(200);
  if ((await J("surfMarks()")).length !== 1) fail("Esc did not remove the last mark");
  if ((await ev("surfFit().kind")) !== "flat") fail("one mark is not a flat surface");
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27, modifiers: 8 }); await sleep(200);
  if ((await J("surfMarks()")).length !== 0) fail("shift+Esc did not remove every mark");

  // ---- 2. the fits, on marks put on known surfaces (µm: x = px/2, y = py/2, z = slice) ----------------
  // a plane: z = 10 + 0.1 x + 0.05 y  ->  slice = 10 + px/20 + py/40
  await ev(`V.vol.surf[unit.path] = [[0,0,0],[0,40,0],[0,0,80],[0,80,40],[0,40,80]].map(([_, px, py]) => [10 + px/20 + py/40, py, px]); orthoDraw(); 'ok'`);
  let F = await J("(f => ({kind:f.kind, gx:f.gx, gy:f.gy, rms:f.rms, z0:f.z(0,0), z1:f.z(50,50)}))(surfFit())");
  const close = (a, b, e = 1e-6) => Math.abs(a - b) < e;
  if (F.kind !== "plane" || !close(F.gx, .1) || !close(F.gy, .05) || !close(F.rms, 0) || !close(F.z0, 10) || !close(F.z1, 17.5))
    fail("the plane fit is off: " + JSON.stringify(F));
  let info = await ev("$('oSurfInfo').textContent");
  const tilt = (Math.atan(Math.hypot(.1, .05)) * 180 / Math.PI).toFixed(1);
  if (!info.includes(`plane · tilt ${tilt}°`)) fail("the info does not give the tilt: " + info);
  // a curved one: slice = 5 + px²/400 + py/40 on a 5 × 3 grid
  await ev(`V.vol.surf[unit.path] = []; for (const px of [0,20,40,60,80]) for (const py of [0,40,80]) V.vol.surf[unit.path].push([5 + px*px/400 + py/40, py, px]); orthoDraw(); 'ok'`);
  F = await J("(f => ({kind:f.kind, rms:f.rms, a:f.z(50,0), b:f.z(20,10), c:f.z(0,40)}))(surfFit())");
  if (F.kind !== "curved" || !close(F.rms, 0, 1e-5) || !close(F.a, 30, 1e-4) || !close(F.b, 5 + 1600/400 + .5, 1e-4) || !close(F.c, 7, 1e-4))
    fail("the curved fit is off: " + JSON.stringify(F));
  // marks along one cut only (one y): the fit stays level along y instead of failing
  await ev(`V.vol.surf[unit.path] = [0,20,40,60,80,100].map(px => [5 + px*px/400, 64, px]); orthoDraw(); 'ok'`);
  F = await J("(f => f && ({kind:f.kind, rms:f.rms, a:f.z(50,32), b:f.z(50,0), c:f.z(50,60)}))(surfFit())");
  if (!F || F.kind !== "curved" || !close(F.rms, 0, 1e-3) || !close(F.a, 30, 1e-2) || !close(F.b, F.a, 1e-2) || !close(F.c, F.a, 1e-2))
    fail("marks along one cut do not give a level, exact fit: " + JSON.stringify(F));

  // ---- 3. depth: by hand, both ways; by brightness, both ways -------------------------------------
  await ev(`V.vol.surf[unit.path] = [[10,0,0]]; V.vol.pts[unit.path] = [[25,0,0],[4,0,0]]; 'ok'`);
  await ev("V.vol.surfTis = 1; orthoDraw(); 'ok'");
  let d = await J("volPts().map(q => surfDepth(q))");
  if (!close(d[0], 15) || !close(d[1], -6)) fail("depth with the tissue toward the last slice is off: " + d);
  await ev("$('oSurfTis').click(); 'ok'");            // 1 -> 0 (auto)
  if (await ev("V.vol.surfTis") !== 0) fail("the tissue button does not cycle to auto");
  await ev("$('oSurfTis').click(); 'ok'");            // 0 -> -1
  d = await J("volPts().map(q => surfDepth(q))");
  if (await ev("V.vol.surfTis") !== -1 || !close(d[0], -15) || !close(d[1], 6)) fail("depth with the tissue toward slice 0 is off: " + d);
  info = await ev("$('oSurfInfo').textContent");
  if (!info.includes("3D points: 1: -15.0 µm · 2: 6.0 µm") || !info.includes("toward slice 0 (set)")) fail("the info does not give the points' depth: " + info);
  // brightness: the tissue made bright below slice 10, then above it
  for (const [deep, side] of [[true, 1], [false, -1]]) {
    const got = await J(`(()=>{const keep = volBytes, [D,H,W] = volMeta.shape, a = new Uint8Array(D*H*W);
      for (let z = 0; z < D; z++) a.fill((z > 10) === ${deep} ? 200 : 20, z*H*W, (z+1)*H*W);
      volBytes = [a]; V.vol.surfTis = 0; _surfSide.key = ""; const s = surfSide(surfFit()); volBytes = keep; _surfSide.key = ""; return s;})()`);
    if (got.side !== side || got.how !== "bright") fail(`the brighter side was not found (${deep ? "deep" : "shallow"} tissue): ` + JSON.stringify(got));
  }

  // ---- 4. the CSV --------------------------------------------------------------------------------
  await ev("V.vol.surfTis = 1; orthoDraw(); 'ok'");
  const csv = await ev(`new Promise(ok => { const keep = URL.createObjectURL, click = HTMLAnchorElement.prototype.click;
    URL.createObjectURL = b => { b.text().then(ok); return "blob:test"; }; HTMLAnchorElement.prototype.click = function () { window.__name = this.download; };
    surfCsv(); URL.createObjectURL = keep; HTMLAnchorElement.prototype.click = click; })`);
  const rows = csv.trim().split("\n").filter(l => !l.startsWith("#"));
  if (rows[0] !== "kind,n,slice,px,py,x_um,y_um,z_um,surface_z_um,depth_um") fail("the CSV header: " + rows[0]);
  if (rows[1] !== "mark,1,10,0,0,0.000,0.000,10.000,10.000,0.000" || rows[2] !== "point,1,25,0,0,0.000,0.000,25.000,10.000,15.000" || rows[3] !== "point,2,4,0,0,0.000,0.000,4.000,10.000,-6.000")
    fail("the CSV rows: " + JSON.stringify(rows));
  if (!/surface\.csv$/.test(await ev("window.__name"))) fail("the CSV's name: " + await ev("window.__name"));

  // ---- 5. kept with the view --------------------------------------------------------------------
  await ev("saveView(); 'ok'"); await sleep(900);
  await open(); await sleep(500);
  const kept = await J(`(()=>{const u = FILE.units.find(u => u.z_step_um).path; return {m: V.vol.surf[u], tis: V.vol.surfTis, on: V.vol.oSurf};})()`);
  if (JSON.stringify(kept) !== JSON.stringify({ m: [[10, 0, 0]], tis: 1, on: true })) fail("the marks did not survive a reload: " + JSON.stringify(kept));
  await shot("reloaded");

  await ev("V.vol = volState(null); saveView(); 'ok'"); await sleep(700);
  console.log("  surface: clicks, plane, curve, one-cut, depth both ways, brightness both ways, csv, reload — ok");
  console.log("  console errors:", errors.length, errors.slice(0,2));
  chrome.kill(); process.exit(errors.length ? 1 : 0);
})();
