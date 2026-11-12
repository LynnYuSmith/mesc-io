"use strict";
/* Smooth playback (12 Nov 2026) in a real Chrome, over CDP. NOT collected by pytest: needs Chrome and a
   running viewer on a recording of a few hundred frames or more.

     mesc-io view recording.mesc --port 8041 --no-browser &
     node tests/view_playback_real_chrome.js http://127.0.0.1:8041/ [unit index]

   The old player (one PNG per request, a tick skipped while one is on its way) and the new one (blocks of
   bytes, buffered ahead, a frame waited for and never skipped) each play 5 s, on a fast line and on a lab-PC
   line (80 ms per request, CPU 4× slower). Held:
   * the new player never skips a frame, and on the slow line it shows at least twice as many frames as the old;
   * the picture it shows is the PNG path's, pixel for pixel (the frame on screen when ▶ is pressed again). */
const { spawn } = require("node:child_process"); const http = require("node:http");
const URL_ = process.argv[2], UNIT = +(process.argv[3] || 0), SETUP = process.argv[4] || "";   // e.g. "V.avg=10; V.overlay=true;"
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; const PORT = 9341;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const getJSON = (u) => new Promise((res, rej) => http.get(u, r => { let b = ""; r.on("data", d => b += d); r.on("end", () => res(JSON.parse(b))); }).on("error", rej));

const OLD_PLAY = String.raw`
window.__oldPlay = function () {
  showFrames();
  player.start({ range: [0, unit.frames - 1], frame: () => V.frame, isBusy: () => frameLoader.busy,
                 onFrame: f => { V.frame = f; $("frame").value = V.frame; draw(); plotTraces(); } });
};
window.__log = function (ms) {               // every animation frame: which frame is on screen
  const log = []; const t0 = performance.now();
  return new Promise(res => { (function step() { log.push([performance.now() - t0, V.frame]); if (performance.now() - t0 < ms) requestAnimationFrame(step); else res(log); })(); });
};`;

function summarise(log) {
  const ch = []; let last = log[0][1];
  for (const [t, f] of log) if (f !== last) { ch.push([t, f, f - last]); last = f; }
  const steps = ch.map(c => c[2]), gaps = ch.slice(1).map((c, i) => c[0] - ch[i][0]);
  return { shown: ch.length, skipped: steps.filter(s => s > 1).reduce((a, s) => a + s - 1, 0),
           maxGapMs: Math.round(Math.max(0, ...gaps)), medGapMs: Math.round(gaps.sort((a, b) => a - b)[gaps.length >> 1] || 0) };
}

(async () => {
  const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=" + PORT, "--no-first-run", "--user-data-dir=/tmp/view_playback_profile", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
  process.on("exit", () => { try { chrome.kill(); } catch (_) {} });
  let targets; for (let i = 0; i < 30; i++) { try { targets = await getJSON(`http://127.0.0.1:${PORT}/json`); break; } catch { await sleep(300); } }
  const ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let id = 0; const pending = new Map(); const errors = [];
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    else if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text); };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text + " " + (r.result.exceptionDetails.exception || {}).description); return r.result.result.value; };
  let bad = 0; const fail = (m) => { console.error("  FAIL: " + m); bad++; };
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
  await send("Page.navigate", { url: URL_ }); await sleep(2500);
  await ev(OLD_PLAY);
  await ev(`pick(${UNIT}); V.proj=""; V.avg=1; V.traceZoom=null; ${SETUP} showFrames(); 'ok'`); await sleep(1500);
  console.log("unit", await ev(`unit.path + " " + unit.width + "x" + unit.height + " · " + unit.frames + " frames · palette " + paletteFor(V.ch)`));

  const res = {};
  for (const [line, lat, cpu] of [["fast", 0, 1], ["lab PC", 80, 4]]) {
    await send("Network.emulateNetworkConditions", { offline: false, latency: lat, downloadThroughput: -1, uploadThroughput: -1 });
    await send("Emulation.setCPUThrottlingRate", { rate: cpu });
    for (const who of ["old", "new"]) {
      await ev(`V.frame = 100; $("frame").value = 100; draw(); 'ok'`); await sleep(1200);
      await ev(who === "old" ? "__oldPlay(); 'ok'" : "togglePlay(); 'ok'");
      const log = await ev(`__log(5000)`);
      await ev(`player.stop(); stream.stop(); $("playBtn").textContent = "▶"; 'ok'`);
      res[line + " " + who] = summarise(log);
    }
  }
  await send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await send("Emulation.setCPUThrottlingRate", { rate: 1 });
  console.table(res);
  if (res["fast new"].skipped || res["lab PC new"].skipped) fail("the new player skipped frames");
  if (!(res["lab PC new"].shown >= 2 * res["lab PC old"].shown)) fail("on the lab-PC line the new player is not at least twice as smooth");
  if (!(res["fast new"].shown >= 100)) fail("the new player showed fewer than 100 frames in 5 s on a fast line");

  // pixels: the frame the buffer put on screen vs the PNG path's picture of the same frame
  const px = JSON.parse(await ev(`(async () => {
    togglePlay(); await new Promise(r => setTimeout(r, 1500));
    stream.stop(); player.stop();                      // stop WITHOUT togglePlay: it would redraw through the PNG path
    const f = V.frame, a = _streamCanvas.getContext("2d").getImageData(0, 0, unit.width, unit.height).data;
    imgEl = null; draw(); await new Promise(r => setTimeout(r, 1500));
    const c = document.createElement("canvas"); c.width = unit.width; c.height = unit.height;
    const g = c.getContext("2d"); g.drawImage(imgEl, 0, 0); const b = g.getImageData(0, 0, unit.width, unit.height).data;
    let diff = 0; for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) diff++;
    $("playBtn").textContent = "▶";
    return JSON.stringify({ frame: f, sameFrame: V.frame === f, bytes: a.length, diff });
  })()`));
  console.log("pixels:", px);
  if (!px.sameFrame) fail("the frame moved while comparing");
  if (px.diff !== 0) fail(`${px.diff} bytes differ between the buffered frame and the PNG path`);
  if (errors.length) fail("page errors: " + errors.join(" | "));
  console.log(bad ? `${bad} FAILED` : "playback: all held");
  chrome.kill(); process.exit(bad ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
