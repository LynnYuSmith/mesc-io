/* mesc-io engine — image.js: a recording's picture on a host's canvas.
 *
 * The parts every host needs and none should rewrite: where an image pixel lands on screen under a
 * zoom (and MESc's upside-down view), where a mouse position falls in the image, drawing a frame
 * with whole pixels, and loading frames so a slider dragged across 30 positions asks for ONE frame
 * at a time, not 30. No page state in here: the viewer and the CIP playground both pass in what
 * they have.
 *
 * A classic script, like api.js: <script src="static/image.js"></script> → MescIO.image.
 */
(function (root) {
  "use strict";

  /* Image → screen. The zoom rectangle {x, y, w, h} (image px; w = 0 means "the whole image") is
     fitted into the stage W × H and centred. With flipY the picture is drawn upside down, as MESc
     draws it (row 0 at the bottom); an image coordinate still means the file's own row — only sy()
     and toImage() know about the flip. */
  function mapping(W, H, zoom, width, height, flipY) {
    const z = zoom && zoom.w ? zoom : { x: 0, y: 0, w: width, h: height };
    const k = Math.min(W / z.w, H / z.h), fy = !!flipY, uh = height;
    const ox = (W - z.w * k) / 2 - z.x * k;
    const oy = (H - z.h * k) / 2 - (fy ? uh - z.y - z.h : z.y) * k;   // the top of the picture on screen
    const sy = y => oy + (fy ? uh - y : y) * k;
    return { k, ox, oy, W, H, fy, sy };
  }

  // Screen → image: a mouse position (client coordinates) over the stage whose box is `rect`.
  function toImage(clientX, clientY, rect, m, height) {
    const y = (clientY - rect.top - m.oy) / m.k;
    return [(clientX - rect.left - m.ox) / m.k, m.fy ? height - y : y];
  }

  // The picture itself, whole pixels (no smoothing: a pixel stays a pixel), flipped when asked.
  function drawFrame(g, img, m, width, height) {
    if (!img) return;
    g.imageSmoothingEnabled = false;
    if (m.fy) { g.save(); g.setTransform(1, 0, 0, -1, 0, 2 * m.oy + height * m.k); }
    g.drawImage(img, m.ox, m.oy, width * m.k, height * m.k);
    if (m.fy) g.restore();
  }

  /* At most one frame in flight. A request made while one is on its way only marks that another is
     wanted; when the first lands, `again()` is called and the host asks for wherever its slider is
     THEN. `key` names what is being shown (the URLs + palettes): asking for the shown key again
     answers "same" and loads nothing.
       request(key, urls, { isCurrent, onLoad(images), onError(), again })  → "loading" | "queued" | "same"
     `isCurrent()` lets the host drop a frame that landed after it moved on (another unit). */
  function createLoader(makeImage) {
    const mk = makeImage || (() => new Image());
    const L = { key: "", busy: false, wanted: false };
    L.request = function (key, urls, cb) {
      if (key !== L.key && L.busy) { L.wanted = true; return "queued"; }
      if (key === L.key) return "same";
      L.key = key; L.busy = true; L.wanted = false;
      const landed = () => { L.busy = false; if (L.wanted) { L.wanted = false; if (cb.again) cb.again(); } };
      const still = () => L.key === key && (!cb.isCurrent || cb.isCurrent());
      Promise.all(urls.map(u => new Promise((ok, bad) => { const im = mk(); im.onload = () => ok(im); im.onerror = bad; im.src = u; })))
        .then(ims => { if (still()) cb.onLoad(ims); landed(); })
        .catch(() => { if (still() && cb.onError) cb.onError(); landed(); });
      return "loading";
    };
    return L;
  }

  root.MescIO = root.MescIO || {};
  root.MescIO.image = { mapping, toImage, drawFrame, createLoader };
})(typeof window !== "undefined" ? window : globalThis);
