/* mesc-io engine — api.js: every route of the engine, addressed through ONE base.
 *
 * The standalone viewer serves the engine at the root ("" → /api/frame/…); a host application
 * mounts the same engine under a prefix ("/mesc" → /mesc/api/frame/…). Every URL the viewer or a
 * host builds goes through `api.url(path)`, so the prefix is said once.
 *
 * The base is found by itself: this file is served by the engine as <base>/static/api.js, so
 * the base is wherever this script was loaded from, minus "/static/api.js". Pass it explicitly
 * to createApi(base) to override.
 *
 * A classic script (not an ES module), on purpose: the viewer's own script is classic, and its
 * real-Chrome checks read its top-level state (V, ROIS, unit …) — a module would hide that.
 * Usage:  <script src="static/api.js"></script>   then   const API = MescIO.createApi();
 */
(function (root) {
  "use strict";
  const doc = root.document;
  const self = doc && doc.currentScript && doc.currentScript.src ? doc.currentScript.src : "";

  // "http://host:8040/mesc/static/api.js" → "/mesc";  "http://host:8031/static/api.js" → ""
  function baseFromScript(src) {
    if (!src) return "";
    let path;
    try { path = new URL(src).pathname; } catch (_) { return ""; }
    const i = path.lastIndexOf("/static/");
    return i > 0 ? path.slice(0, i) : "";
  }

  function createApi(base) {
    const b = (base === undefined || base === null ? baseFromScript(self) : String(base)).replace(/\/+$/, "");
    const url = (path) => b + path;
    const json = async (path, opts) => (await fetch(url(path), opts)).json();
    const send = (method, path, payload) =>
      fetch(url(path), { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    return {
      base: b,
      url,
      // the routes, as URLs (for <img src>, downloads, cache keys) …
      frameUrl: (unitPath, ch, frame, query) => url(`/api/frame/${unitPath}/${ch}/${frame}` + (query ? `?${query}` : "")),
      meanUrl: (unitPath, ch, query) => url(`/api/mean/${unitPath}/${ch}` + (query ? `?${query}` : "")),
      thumbUrl: (unitPath, ch, query) => url(`/api/thumb/${unitPath}/${ch}` + (query ? `?${query}` : "")),
      // … and as calls
      file: () => json("/api/file"),
      metadata: (unitPath) => json(`/api/metadata/${unitPath}`),
      pixel: (unitPath, ch, query) => json(`/api/pixel/${unitPath}/${ch}?${query}`),
      rois: (unitPath) => json(`/api/rois?unit=${encodeURIComponent(unitPath)}`),
      putRois: (unitPath, rois) => send("PUT", "/api/rois", { unit: unitPath, rois }),
      traces: (unitPath, ch, query) => json(`/api/traces/${unitPath}/${ch}` + (query ? `?${query}` : "")),
      send,
    };
  }

  root.MescIO = root.MescIO || {};
  root.MescIO.createApi = createApi;
  root.MescIO._baseFromScript = baseFromScript;      // exposed for the tests
})(typeof window !== "undefined" ? window : globalThis);
