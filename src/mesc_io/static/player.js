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

  root.MescIO = root.MescIO || {};
  root.MescIO.player = { nextFrame, stepFrame, slideWindow, clampAvg, createPlayer, AVG_MAX };
})(typeof window !== "undefined" ? window : globalThis);
