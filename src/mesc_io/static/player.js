/* mesc-io engine — player.js: moving through a recording's frames.
 *
 * Play (a timer that waits for the disk: a tick while a frame is still on its way is skipped, so the
 * recording never runs ahead of what is shown), step with the arrows (×10 with shift), slide a
 * zoomed time window, and the averaging window n. No page state: the host says where the frame is,
 * what range to loop over, and what to do with a new frame.
 *
 * A classic script, like api.js: <script src="static/player.js"></script> → MescIO.player.
 */
(function (root) {
  "use strict";

  const AVG_MAX = 999;

  // The next frame of playback: one on, back to the start of the range past its end.
  const nextFrame = (f, a, b) => (f + 1 > b ? a : f + 1);

  // An arrow press: one frame (ten with shift), never past either end.
  const stepFrame = (f, dir, big, frames) => Math.max(0, Math.min(frames - 1, f + dir * (big ? 10 : 1)));

  // An arrow press while zoomed into time slides the window by a tenth of its span (half with
  // shift), keeping its width, never past either end of the n samples.
  function slideWindow(win, dir, big, n) {
    const [a, b] = win, span = b - a, step = Math.max(1, Math.round(span * (big ? 0.5 : 0.1)));
    const a2 = Math.max(0, Math.min(n - 1 - span, a + dir * step));
    return [a2, a2 + span];
  }

  // The averaging window as typed: a whole number of frames, 1 … 999; anything unreadable is 1.
  const clampAvg = n => Math.max(1, Math.min(AVG_MAX, Math.round(+n) || 1));

  /* Playback. start({ range: [a, b], frame: () => current, isBusy: () => bool, onFrame: f => … })
     ticks every intervalMs; stop() ends it; `playing` says whether it runs. */
  function createPlayer(intervalMs) {
    const ms = intervalMs || 40;
    let timer = null;
    const P = {
      get playing() { return timer !== null; },
      start(o) {
        P.stop();
        const [a, b] = o.range;
        timer = setInterval(() => {
          if (o.isBusy && o.isBusy()) return;              // the disk sets the pace, not the timer
          o.onFrame(nextFrame(o.frame(), a, b));
        }, ms);
        if (timer === null || timer === undefined) timer = 0;   // some timers return 0; still "playing"
      },
      stop() { if (timer !== null) { clearInterval(timer); timer = null; } },
    };
    return P;
  }

  /* Smooth playback (her ask, 12 Nov 2026: «плавний програш відео як у репорті»). createPlayer asks
     for one frame, waits for it, then asks for the next: on a lab PC reading a network drive every
     frame pays the whole round trip, ticks are skipped unevenly and the picture jerks. This one
     keeps frames AHEAD of the one on screen, fetched in blocks (one request per `block` frames),
     and shows them at a steady interval. When the next frame is not there yet it waits on that
     frame — it never skips one — and says so through onWait.

     start({ range: [a, b], frame: () => current,
             key: () => what the frames depend on (unit, channels, window, avg…) — a change drops the buffer,
             fetch: (start, count) => Promise<array of `count` payloads, one per frame>,
             onFrame: (f, payload) => show it, onWait: waiting => …, onError: err => … })
     `block` frames per request, at most `inflight` requests at once, at most `ahead` frames buffered
     beyond the one on screen. A block never crosses the end of the range; past it, fetching goes on
     from the start, so a loop plays through without a stop. */
  function createStreamPlayer(opts) {
    const o0 = opts || {};
    const ms = o0.intervalMs || 40, block = o0.block || 16, maxIn = o0.inflight || 2, ahead = o0.ahead || 64;
    let timer = null, gen = 0, buf = new Map(), inflight = 0, fetchAt = 0, key = "", waiting = false, o = null;
    const len = (from, to, a, b) => (to >= from ? to - from : (b - from + 1) + (to - a));   // frames from → to, looping
    function reset(from) { gen++; buf = new Map(); inflight = 0; fetchAt = from; key = o.key ? o.key() : ""; }
    function pump(want) {
      const [a, b] = o.range, span = b - a + 1, lim = Math.min(ahead, span);   // a loop shorter than `ahead` is buffered whole (the guard ends the lap)
      for (let guard = Math.ceil(span / block) + 1; guard > 0 && inflight < maxIn && len(want, fetchAt, a, b) < lim; guard--) {
        const s = fetchAt, count = Math.min(block, b - s + 1), g = gen;
        fetchAt = s + count > b ? a : s + count;
        if (buf.has(s) && buf.has(s + count - 1)) continue;          // a short loop: already here
        inflight++;
        Promise.resolve(o.fetch(s, count)).then(arr => {
          if (g !== gen) return;
          inflight--;
          arr.forEach((p, k) => buf.set(s + k, p));
        }, err => {
          if (g !== gen) return;
          inflight--;
          P.stop();
          if (o.onError) o.onError(err);
        });
      }
    }
    function tick() {
      const [a, b] = o.range, cur = o.frame();
      if (o.key && o.key() !== key) reset(nextFrame(cur, a, b));
      const want = nextFrame(cur, a, b);
      if (buf.has(want)) {
        const p = buf.get(want);
        for (const f of buf.keys()) if (len(want, f, a, b) > ahead + block) buf.delete(f);   // behind the cursor
        buf.delete(cur);
        if (waiting) { waiting = false; if (o.onWait) o.onWait(false); }
        o.onFrame(want, p);
      } else if (!waiting) { waiting = true; if (o.onWait) o.onWait(true); }
      pump(nextFrame(o.frame(), a, b));
    }
    const P = {
      get playing() { return timer !== null; },
      get buffered() { return buf.size; },
      start(o1) {
        P.stop();
        o = o1;
        const [a, b] = o.range;
        reset(nextFrame(o.frame(), a, b));
        pump(fetchAt);
        timer = setInterval(tick, ms);
        if (timer === null || timer === undefined) timer = 0;
      },
      stop() {
        if (timer !== null) { clearInterval(timer); timer = null; }
        gen++; buf = new Map(); inflight = 0;
        if (waiting) { waiting = false; if (o && o.onWait) o.onWait(false); }
      },
    };
    return P;
  }

  root.MescIO = root.MescIO || {};
  root.MescIO.player = { nextFrame, stepFrame, slideWindow, clampAvg, createPlayer, createStreamPlayer, AVG_MAX };
})(typeof window !== "undefined" ? window : globalThis);
