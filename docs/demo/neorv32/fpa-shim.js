// Layout helper for fpa's design.html, injected by the demo page between the inlined ELK
// bundle and the viewer script. fpa's viewer and its output are unchanged; this only
// replaces the global ELK it calls with a wrapper that
//  * answers from layouts.json (computed at build time by the same ELK on the same graphs),
//    so the 37-block neorv32_top level appears at once instead of after about a minute of
//    main-thread ELK work, and
//  * runs any other layout (other toggles, disabled blocks) in a Web Worker, so the
//    simulation panel stays responsive while it runs.
// Cache key: the ELK input graph without 'width' and 'x' (those depend on the local fonts;
// the drawing takes node sizes and port positions from the layout result, so a cached
// layout is self-consistent). Mode 'record' (build time) stores every layout it computes.
(function () {
  'use strict';
  var RealELK = window.ELK;
  if (!RealELK) return;
  var mode = window.__FPA_SHIM_MODE || 'replay';
  var cache = null;
  try { cache = (window.parent && window.parent !== window && window.parent.__fpaLayouts) || null; } catch (e) { cache = null; }
  var rec = window.__fpaRec = {};
  window.__fpaLayoutPending = 0;
  window.__fpaLayoutStats = { hit: 0, worker: 0, main: 0 };

  function hash(s) { // cyrb53
    var h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (var i = 0; i < s.length; i++) { var c = s.charCodeAt(i); h1 = Math.imul(h1 ^ c, 2654435761); h2 = Math.imul(h2 ^ c, 1597334677); }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (h2 >>> 0).toString(16).padStart(8, '0') + (h1 >>> 0).toString(16).padStart(8, '0');
  }
  function keyOf(g) {
    var s = JSON.stringify(g, function (k, v) { return k === 'width' || k === 'x' ? undefined : v; });
    return hash(s) + ':' + s.length;
  }
  // keep only what the viewer's draw() reads
  function slim(r) {
    return {
      width: r.width, height: r.height,
      children: (r.children || []).map(function (n) { return { id: n.id, x: n.x, y: n.y, width: n.width, height: n.height }; }),
      edges: (r.edges || []).map(function (e) {
        var o = { id: e.id, sections: (e.sections || []).map(function (s) {
          var q = { startPoint: s.startPoint, endPoint: s.endPoint };
          if (s.bendPoints && s.bendPoints.length) q.bendPoints = s.bendPoints;
          return q;
        }) };
        if (e.junctionPoints && e.junctionPoints.length) o.junctionPoints = e.junctionPoints;
        return o;
      })
    };
  }

  var worker = null, seq = 0, waits = {};
  function viaWorker(g) {
    if (!worker) {
      var src = '';
      for (var i = 0; i < document.scripts.length; i++) if (document.scripts[i].textContent.length > 500000) { src = document.scripts[i].textContent; break; }
      var code = src + '\n;self.onmessage = function (e) { new ELK().layout(e.data.g).then(' +
        'function (r) { self.postMessage({ id: e.data.id, r: r }); }, function (err) { self.postMessage({ id: e.data.id, err: String(err) }); }); };';
      worker = new Worker(URL.createObjectURL(new Blob([code], { type: 'text/javascript' })));
      worker.onmessage = function (e) {
        var w = waits[e.data.id]; delete waits[e.data.id];
        window.__fpaLayoutPending--;
        if (e.data.err) w.rej(new Error(e.data.err)); else w.res(e.data.r);
      };
    }
    var id = ++seq;
    window.__fpaLayoutPending++;
    return new Promise(function (res, rej) { waits[id] = { res: res, rej: rej }; worker.postMessage({ id: id, g: g }); });
  }

  function Wrapped() {}
  Wrapped.prototype.layout = function (g) {
    var k = keyOf(g);
    if (mode === 'record') {
      return new RealELK().layout(g).then(function (r) { rec[k] = slim(r); return r; });
    }
    if (cache && cache[k]) { window.__fpaLayoutStats.hit++; return Promise.resolve(JSON.parse(JSON.stringify(cache[k]))); }
    var big = (g.children || []).length > 24 || (g.edges || []).length > 120;
    if (big && typeof Worker !== 'undefined') { window.__fpaLayoutStats.worker++; return viaWorker(g); }
    window.__fpaLayoutStats.main++;
    return new RealELK().layout(g);
  };
  window.ELK = Wrapped;
})();
