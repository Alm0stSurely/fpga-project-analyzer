// Build step: compute fpa's ELK layouts once, for every level of the diagram that exists in
// this configuration, and save them as layouts.json (see web/fpa-shim.js).
// usage: node record_layouts.mjs <devtools port> <file:// url of design.html with the shim in record mode>
//        <fpa-map.json> <out layouts.json>
import { readFileSync, writeFileSync } from 'node:fs';

const [port, url, mapFile, out] = process.argv.slice(2);
const phantoms = JSON.parse(readFileSync(mapFile, 'utf8')).phantoms;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let id = 0;
const pend = new Map();
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } });
const send = (method, params = {}) => { const i = ++id; ws.send(JSON.stringify({ id: i, method, params })); return new Promise((r) => pend.set(i, r)); };
const ev = async (x) => {
  const m = await send('Runtime.evaluate', { expression: x, returnByValue: true });
  if (m.error || m.result.exceptionDetails) throw new Error(x + ': ' + JSON.stringify(m.error || m.result.exceptionDetails));
  return m.result.result.value;
};
async function waitFor(x, ms) {
  const t0 = Date.now();
  while (!(await ev(x).catch(() => false))) { if (Date.now() - t0 > ms) throw new Error('timeout: ' + x); await sleep(200); }
  return Date.now() - t0;
}

await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: url + '#/' });
await waitFor('window.__fpa_ready === true', 120000);
// every level that has children and exists in this configuration, as the viewer walks them
const levels = await ev(`(() => {
  const D = JSON.parse(document.getElementById('fpa-data').textContent), defs = D.defs, out = [[]];
  const body = (d) => (!d.insts.length && d.impl && defs[d.impl]) ? defs[d.impl] : d;
  const ph = ${JSON.stringify(phantoms)}, isPh = (p) => ph.some((q) => p === q || p.startsWith(q + '/'));
  (function walk(d, parts) {
    for (const i of body(d).insts) {
      const p = parts.concat(i.name), cd = defs[i.def];
      if (isPh('/' + p.join('/')) || !body(cd).insts.length) continue;
      out.push(p); walk(cd, p);
    }
  })(defs[D.top], []);
  return out;
})()`);
for (const parts of levels) {
  const want = JSON.stringify(parts);
  await ev(`(window.__fpa.go(${want}), 1)`);
  const ms = await waitFor(`window.__fpa_ready === true && JSON.stringify(window.__fpa.state.path) === ${JSON.stringify(want)}`, 600000);
  console.log(`  ${(ms / 1000).toFixed(1).padStart(6)} s  /${parts.join('/')}`);
}
const rec = await ev('JSON.stringify(window.__fpaRec)');
writeFileSync(out, rec);
console.log(`layouts: ${levels.length} levels, ${Object.keys(JSON.parse(rec)).length} layouts, ${rec.length} bytes`);
ws.close();
process.exit(0);
