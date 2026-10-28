/* The mosaic, in a real Chrome: every z-stack tile of a file laid out by the stage, stitched from
   the overlaps, moved by hand, flattened on the marked surfaces, cut out — on the synthetic mosaic
   (tools/make_synthetic.py --mosaic), whose tiles are each off by a known few pixels and slices.

     python tools/make_synthetic.py --mosaic synthetic_mosaic.mesc
     mesc-io view synthetic_mosaic.mesc --port 8034 --no-browser &
     node tests/view_mosaic_real_chrome.js http://127.0.0.1:8034/ <out prefix>

   Tiles: 3 × 2, 96 px of 0.5 µm, 40 slices; the errors (dx px, dy px, dz slices) are
   (0,0,0) (3,-2,2) (-4,1,-1) (2,4,3) (-3,-3,1) (5,2,-2). */
const { spawn } = require("node:child_process"); const http = require("node:http"); const fs = require("node:fs");
const URL_ = process.argv[2], OUT = process.argv[3] || "/tmp/mosaic";
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9352;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data",d=>b+=d); r.on("end",()=>res(JSON.parse(b))); }).on("error", rej));
// a bouton of axon 1 at slice bz, where make_synthetic.py puts it: (z, y, x), sub-pixel
const bouton = bz => [bz, 30 + 60 * bz / 47, 20 + 80 * bz / 47];
(async () => {
  const chrome = spawn(CHROME, ["--headless=new","--remote-debugging-port="+PORT,"--no-first-run",
    "--user-data-dir=/tmp/mosaic_profile","--window-size=1500,1000","--enable-unsafe-swiftshader",
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
  const open = async () => { await send("Page.navigate",{url:URL_}); await sleep(2500); };
  await open();
  const ERR = [[0,0,0],[3,-2,2],[-4,1,-1],[2,4,3],[-3,-3,1],[5,2,-2]];
  const paths = await J("mosTiles().map(u => u.path)");
  if (paths.length !== 6) fail("not six tiles: " + paths.length);
  if (await ev("$('mosBtn').hidden")) fail("the mosaic button is hidden on a file of six tiles");
  // a clean start whatever the saved view holds (an exploratory run leaves flips and zooms behind)
  await ev("V.flipY = false; V.tracesH = 260; V.metaH = 300; V.toolsW = 260; applyStatic(); V.vol = volState(null); V.mos = mosState(null); V.mos.list = false; $('mosBtn').click(); 'ok'");
  if (await ev("$('mosaic').hidden")) fail("the mosaic did not open");
  // a plane loaded: wait for every tile's picture
  const settled = async () => { for (let i = 0; i < 60 && (await ev("$('mosWait').textContent")) !== ""; i++) { await sleep(200); await ev("mosDraw(); 'ok'"); } await sleep(150); };
  await ev("V.mos.plane = 20; mosDraw(); 'ok'"); await settled();

  // ---- 1. placed by the stage; the same geometry as the Python side, rounding included --------------
  let G = await J("(()=>{const G=mosGeom(); return {W:G.W,H:G.H,z:[G.z0,G.z1],pl:mosTiles().map(u=>{const p=G.place[u.path]; return [p.c0,p.r0,p.z0];})}})()");
  if (JSON.stringify(G) !== JSON.stringify({W:240,H:168,z:[0,40],pl:[[0,0,0],[72,0,0],[144,0,0],[0,72,0],[72,72,0],[144,72,0]]})) fail("the stage layout: " + JSON.stringify(G));
  await ev(`V.mos.layout.tiles = {}; ${JSON.stringify(ERR)}.forEach((e, i) => mosSet(mosTiles()[i].path, {dx: e[0] * .5, dy: e[1] * .5, dz: e[2]})); mosSet(mosTiles()[1].path, {dx: 1.75}); 'ok'`);
  G = await J("(()=>{const G=mosGeom(); return {W:G.W,H:G.H,z:[G.z0,G.z1],pl:mosTiles().map(u=>{const p=G.place[u.path]; return [p.c0,p.r0,p.z0];})}})()");
  // python: mesc_io.mosaic.geometry on the same layout
  if (JSON.stringify(G) !== JSON.stringify({W:245,H:174,z:[-2,43],pl:[[0,2,0],[76,0,2],[140,3,-1],[2,78,3],[69,71,1],[149,76,-2]]})) fail("the page's geometry is not the Python one: " + JSON.stringify(G));
  await ev("V.mos.layout.tiles = {}; V.mos.view = {x: 0, y: 0, k: 1}; mosDraw(); 'ok'"); await settled();

  // ---- 2. the picture: each pixel from the tile whose centre is nearest, as the tile's own frame ---
  // grey (one channel), at one screen pixel per mosaic pixel: the canvas must equal the tile PNGs
  // on the uneven layout the tiles really have (seams at odd angles, tiles at odd depths)
  await ev(`${JSON.stringify(ERR)}.forEach((e, i) => mosSet(mosTiles()[i].path, {dx: e[0] * .5, dy: e[1] * .5, dz: e[2]})); 'ok'`);
  await ev("V.mos.chan = 0; V.flipY = false; V.mos.marks = false; mosDraw(); 'ok'"); await settled();
  const cmp = JSON.parse(await ev(`(async () => { const G = mosGeom(), c = $('mosCv'), r = c.getBoundingClientRect(), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data, s = c.width / r.width;
    let n = 0, bad = 0, worst = 0; const ims = {};
    for (const path of G.order) { const p = G.place[path], im = new Image(); im.src = '/api/frame/' + path + '/0/' + (V.mos.plane - p.z0) + '?' + mosWinQ(G, 0) + '&n=1'; await im.decode();
      const t = document.createElement('canvas'); t.width = p.u.width; t.height = p.u.height; const g = t.getContext('2d'); g.drawImage(im, 0, 0); ims[path] = g.getImageData(0, 0, t.width, t.height).data; }
    for (let y = 0; y < G.H; y++) for (let x = 0; x < G.W; x++) {       // every pixel, the seams too
      const o = mosOwner(G, x + .5, y + .5); if (!o) continue;
      const want = ims[o.u.path][4 * ((y - o.r0) * o.u.width + (x - o.c0))], got = d[4 * (Math.round(y * s) * c.width + Math.round(x * s))];
      if (y * s > c.height - 40) continue;                              // the scale bar's corner
      n++; const e = Math.abs(want - got); if (e > 1) bad++; if (e > worst) worst = e; }
    return JSON.stringify({ n, bad, worst }); })()`));
  if (!(cmp.n >= 30000) || cmp.bad !== 0) fail("the canvas is not the tiles' frames under nearest-centre seams: " + JSON.stringify(cmp));
  await shot("stage");
  await ev("V.mos.layout.tiles = {}; V.mos.marks = true; mosDraw(); 'ok'");

  // ---- 3. auto: stitched from the overlaps, as the Python side does --------------------------------
  await ev("V.mos.chan = 'ov'; V.mos.view = null; $('mosAuto').click(); 'ok'");
  for (let i = 0; i < 50 && (await ev("$('mosAuto').disabled")); i++) await sleep(200);
  const L = await J("mosTiles().map(u => mosEntry(u.path))");
  L.forEach((e, i) => { if (e.dz !== ERR[i][2] || Math.abs(e.dx - ERR[i][0] * .5) > .5 || Math.abs(e.dy - ERR[i][1] * .5) > .5) fail(`auto put tile ${i} at ${JSON.stringify(e)}, it is at ${ERR[i]}`); });
  // every tile where it is (above); the report counts what was used and names what was not believed
  { const rep = await ev("$('mosInfo').textContent"), m = rep.match(/stitched: (\d+) of 11/);
    if (!m || +m[1] < 7 || (+m[1] < 11 && !/not believed/.test(rep))) fail("the stitch report: " + rep); }
  if ((await ev("V.mos.pairs.length")) !== 11) fail("the pairs are not kept for the seams");
  await ev("V.mos.plane = 25; mosDraw(); 'ok'"); await settled(); await shot("stitched");
  // undo goes back to the stage layout; ⌘Z too
  await ev("$('mosUndo').click(); 'ok'");
  if (JSON.stringify(await J("V.mos.layout.tiles")) !== "{}") fail("undo did not bring back the layout before auto");
  await ev(`V.mos.layout = mosState({layout: {tiles: Object.fromEntries(${JSON.stringify(ERR)}.map((e, i) => [mosTiles()[i].path, {dx: e[0] * .5, dy: e[1] * .5, dz: e[2]}]))}}).layout; mosHist = []; mosDraw(); 'ok'`);

  // ---- 4. edit by hand: a drag moves a tile by whole pixels; arrows, [ ], h; a click selects --------
  await ev("V.mos.view = {x: -20, y: -60, k: 2}; V.mos.edit = false; mosDraw(); 'ok'"); await settled();
  const scr = (x, y) => J(`(()=>{const r=$('mosCv').getBoundingClientRect(), s=mosToScreen(mosGeom(), ${x}, ${y}); return {x:r.left+s[0], y:r.top+s[1]};})()`);
  let c4 = await J("(()=>{const p=mosGeom().place[mosTiles()[4].path]; return [p.cx, p.cy];})()");
  let s4 = await scr(c4[0], c4[1]);
  await clickAt(s4.x, s4.y);
  if (await ev("V.mos.sel") !== paths[4]) fail("a click did not select the tile under it");
  const drag = async (a, b, n = 8) => { await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:a.x,y:a.y});
    await send("Input.dispatchMouseEvent",{type:"mousePressed",x:a.x,y:a.y,button:"left",clickCount:1});
    for (let k = 1; k <= n; k++) await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:a.x+(b.x-a.x)*k/n,y:a.y+(b.y-a.y)*k/n,button:"left"});
    await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:b.x,y:b.y,button:"left",clickCount:1}); await sleep(300); };
  const before = await J("mosEntry(mosTiles()[4].path)");
  const v0 = await J("V.mos.view");
  await drag(s4, { x: s4.x + 40, y: s4.y + 20 });                      // edit off: a drag pans
  if (JSON.stringify(await J("mosEntry(mosTiles()[4].path)")) !== JSON.stringify(before)) fail("a drag with edit off moved a tile");
  const v1 = await J("V.mos.view");
  if (Math.abs(v1.x - (v0.x - 20)) > .01 || Math.abs(v1.y - (v0.y - 10)) > .01) fail("a drag with edit off did not pan: " + JSON.stringify([v0, v1]));
  await ev("$('mosEdit').click(); 'ok'");
  s4 = await scr(c4[0], c4[1]);
  await drag(s4, { x: s4.x + 20, y: s4.y - 12 });                      // 10 and −6 mosaic px at k 2
  let after = await J("mosEntry(mosTiles()[4].path)");
  if (Math.abs(after.dx - (before.dx + 5)) > 1e-6 || Math.abs(after.dy - (before.dy - 3)) > 1e-6 || after.dz !== before.dz) fail("the drag did not move the tile by whole pixels: " + JSON.stringify([before, after]));
  const key = async (k, mod = 0) => { await send("Input.dispatchKeyEvent",{type:"keyDown",key:k,code:k,modifiers:mod}); await send("Input.dispatchKeyEvent",{type:"keyUp",key:k,code:k,modifiers:mod}); await sleep(120); };
  await key("ArrowLeft"); await key("ArrowDown", 8); await key("]"); await key("]");
  const ak = await J("mosEntry(mosTiles()[4].path)");
  if (Math.abs(ak.dx - (after.dx - .5)) > 1e-6 || Math.abs(ak.dy - (after.dy + 5)) > 1e-6 || ak.dz !== after.dz + 2) fail("arrows / ] did not nudge: " + JSON.stringify([after, ak]));
  await key("z", 4);                                                   // ⌘Z (meta) undoes one step
  if ((await J("mosEntry(mosTiles()[4].path)")).dz !== after.dz + 1) fail("⌘Z did not undo the last step");
  await key("h");
  if (!(await J("mosEntry(mosTiles()[4].path)")).hidden) fail("h did not hide the selected tile");
  if (await ev("!!mosGeom().place[mosTiles()[4].path]")) fail("a hidden tile is still placed");
  await shot("hidden");
  await ev("$('mosListBtn').click(); 'ok'");
  await ev(`$('mosList').querySelector('.t[data-p="${paths[4]}"] input').click(); 'ok'`);
  if ((await J("mosEntry(mosTiles()[4].path)")).hidden) fail("ticking the tile in the list did not show it again");
  await ev(`$('mosList').querySelector('.t[data-p="${paths[4]}"] .rs').click(); 'ok'`);
  if (JSON.stringify(await J("mosEntry(mosTiles()[4].path)")) !== JSON.stringify({dx:0,dy:0,dz:0,hidden:false})) fail("reset did not bring the tile back to its stage position");
  await ev(`$('mosList').querySelector('.t[data-p="${paths[0]}"] .top').click(); 'ok'`);
  if (await ev("V.mos.layout.seams") !== "order" || (await J("mosGeom().order")).slice(-1)[0] !== paths[0]) fail("top did not put the tile last, seams by order");
  // under order seams the top tile owns its whole overlap
  if ((await J("mosOwner(mosGeom(), 90, 30).u.path")) !== paths[0]) fail("order seams: the top tile does not own its overlap");
  await ev("$('mosSeams').click(); $('mosEdit').click(); 'ok'");

  // ---- 5. crop, planes, TIFF; the layout as JSON ----------------------------------------------------
  await ev("$('mosCrop').click(); 'ok'");
  const a = await scr(20, 30), b = await scr(120, 90);
  await drag(a, b);
  const crop = await J("mosCropPx(mosGeom())");
  if (!crop || Math.abs(crop[0] - 20) > 1 || Math.abs(crop[1] - 30) > 1 || Math.abs(crop[2] - 120) > 1 || Math.abs(crop[3] - 90) > 1) fail("the crop: " + JSON.stringify(crop));
  // the crop stays on the tissue when the layout moves the field's origin
  const cu = await J("V.mos.cropUm");
  await ev(`mosPush(); mosSet(mosTiles()[0].path, {dx: mosEntry(mosTiles()[0].path).dx - 3}); mosDraw(); 'ok'`);
  const crop2 = await J("mosCropPx(mosGeom())");
  if (JSON.stringify(await J("V.mos.cropUm")) !== JSON.stringify(cu) || crop2[0] !== crop[0] + 6 || crop2[2] !== crop[2] + 6) fail("the crop moved with the layout: " + JSON.stringify([crop, crop2]));
  await ev("mosUndo(); 'ok'");
  await ev("$('mosZ0').value = 10; $('mosZ1').value = 12; $('mosZ0').onchange(); 'ok'");
  if (JSON.stringify(await J("V.mos.zr")) !== "[10,12]") fail("the planes from–to");
  await ev("$('mosTif').click(); 'ok'");
  for (let i = 0; i < 50 && (await ev("$('mosTif').disabled")); i++) await sleep(200);
  const info = await ev("$('mosInfo').textContent");
  const m = /written: (\S+\.tif) \(([\d.]+) MB, planes 10–12, the crop\)/.exec(info);
  if (!m) fail("the TIFF was not written: " + info);
  if (!fs.existsSync(m[1]) || fs.statSync(m[1]).size < (crop[2] - crop[0]) * (crop[3] - crop[1]) * 3 * 2 * 4) fail("the TIFF on disk is too small: " + m[1]);
  fs.unlinkSync(m[1]);
  const lay = await ev(`new Promise(ok => { const keep = URL.createObjectURL, click = HTMLAnchorElement.prototype.click;
    URL.createObjectURL = b => { b.text().then(ok); return "blob:test"; }; HTMLAnchorElement.prototype.click = function () {};
    $('mosJson').click(); URL.createObjectURL = keep; HTMLAnchorElement.prototype.click = click; })`);
  const LJ = JSON.parse(lay);
  if (LJ.tiles.length !== 6 || LJ.tiles[3].dz_slices !== 3 || LJ.tiles[3].stage_x_um !== 24 || JSON.stringify(LJ.pixel_um) !== "[0.5,0.5]") fail("the layout JSON: " + lay.slice(0, 300));
  await ev("$('mosCrop').click(); 'ok'"); await key("Escape"); await key("Escape");
  if (await J("V.mos.cropUm") !== null) fail("Esc did not clear the crop");

  // ---- 6. flatten: the marked surfaces onto one plane ----------------------------------------------
  // tile 0's surface at its centre is at slice 9, tile 1's at 6, tile 3's at 12; tile 1 selected
  await ev(`V.vol.surf = {}; [[0, 9], [1, 6], [3, 12]].forEach(([i, z]) => { V.vol.surf[mosTiles()[i].path] = [[z, 48, 48]]; }); V.mos.sel = mosTiles()[1].path; 'ok'`);
  const dz1 = await J("mosEntry(mosTiles()[1].path).dz");
  await ev("$('mosFlat').click(); 'ok'");
  const fl = await J("mosTiles().map(u => mosEntry(u.path).dz)");
  const tgt = 6 + dz1;
  if (fl[0] !== tgt - 9 || fl[1] !== tgt - 6 || fl[3] !== tgt - 12 || fl[2] !== ERR[2][2] || await ev("V.mos.plane") !== tgt) fail(`flatten: ${JSON.stringify(fl)} for the plane ${tgt}`);
  if (!/flattened: the surface of 3 tiles on plane/.test(await ev("$('mosInfo').textContent"))) fail("the flatten report");
  // the hover tells where a tile's surface is
  const h0 = await J("(()=>{const p=mosGeom().place[mosTiles()[0].path]; return [p.cx, p.cy];})()");
  const sh = await scr(h0[0], h0[1]);
  await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:sh.x,y:sh.y}); await sleep(200);
  if (!new RegExp(`its surface here: plane ${tgt}\\.0`).test(await ev("$('mosInfo').textContent"))) fail("the hover does not give the surface: " + await ev("$('mosInfo').textContent"));

  // ---- 7. flipped as MESc: the picture turns over, the clicks still land on the same tile ----------
  await ev("V.flipY = true; mosDraw(); 'ok'"); await settled();
  const s0 = await scr(h0[0], h0[1]);
  await clickAt(s0.x, s0.y);
  if (await ev("V.mos.sel") !== paths[0]) fail("flipped: a click on tile 0's centre did not select it");
  await shot("flipped");
  await ev("V.flipY = false; mosDraw(); 'ok'");

  // ---- 8. kept with the view; a double-click opens the tile in XYZ ---------------------------------
  const kept0 = await J("V.mos.layout");
  await ev("saveView(); 'ok'"); await sleep(900);
  await open();
  if (await ev("$('mosaic').hidden")) fail("the mosaic did not reopen with the view");
  if (JSON.stringify(await J("V.mos.layout")) !== JSON.stringify(kept0)) fail("the layout did not survive a reload");
  await ev("V.mos.view = {x: -20, y: -60, k: 2}; mosDraw(); 'ok'"); await settled();
  const sd = await scr(h0[0] + 72, h0[1] + 10);                          // tile 1, a little below its centre
  await send("Input.dispatchMouseEvent",{type:"mousePressed",x:sd.x,y:sd.y,button:"left",clickCount:1});
  await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:sd.x,y:sd.y,button:"left",clickCount:1});
  await send("Input.dispatchMouseEvent",{type:"mousePressed",x:sd.x,y:sd.y,button:"left",clickCount:2});
  await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:sd.x,y:sd.y,button:"left",clickCount:2}); await sleep(800);
  const op = await J("({u: unit.path, ortho: V.vol.ortho, mos: V.mos.on, f: V.frame})");
  const want1 = await J(`V.mos.plane - mosEntry('${paths[1]}').dz`);
  if (op.u !== paths[1] || !op.ortho || op.mos || op.f !== want1) fail("a double-click did not open the tile in XYZ at its slice: " + JSON.stringify(op));
  await shot("opened");

  await ev("V.mos = mosState(null); V.vol = volState(null); saveView(); 'ok'"); await sleep(700);
  console.log("  mosaic: stage layout = python geometry, canvas = the tiles' frames (" + cmp.n + " px), auto, undo, drag/pan, keys, hide/list/reset/top, crop+TIFF, layout json, flatten, hover, flip, reload, open — ok");
  console.log("  console errors:", errors.length, errors.slice(0,2));
  chrome.kill(); process.exit(errors.length ? 1 : 0);
})();
