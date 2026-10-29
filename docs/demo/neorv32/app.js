// NEORV32 demo page: sim panel (worker-driven) + activity highlight on the fpa diagram (iframe).
const $ = (id) => document.getElementById(id);
const IMEM_MAX = 16384, EXE_SIG = 0x214F454E;   // "NEO!" little-endian, see sw/image_gen/image_gen.c
const st = {
  ready: false, running: true, turbo: false, hz: 0, clock: 1e6, cycles: 0, gpio: 0, names: [],
  uploading: null, current: null, lastError: null, frame: 0,
};

// ---------------------------------------------------------------- terminal
// A small line terminal: CR, LF, BS, TAB, BEL; ANSI escape sequences are skipped.
// Only the current line can change (no cursor-up), so finished lines are appended once.
const term = {
  out: $('term-out'), lineEl: $('term-line'), box: $('term'), input: $('term-in'),
  line: '', col: 0, done: '', esc: 0, chunks: [], lines: 0, dirty: false, bell: false, text: '',
  write(bytes) {
    for (const b of bytes) {
      if (this.esc) {                       // ESC [ params final
        if (this.esc === 1) this.esc = b === 0x5b ? 2 : 0;
        else if (b >= 0x40 && b <= 0x7e) this.esc = 0;
        continue;
      }
      if (b === 13) this.col = 0;
      else if (b === 10) { this.done += this.line + '\n'; this.line = ''; this.col = 0; }
      else if (b === 8) this.col = Math.max(0, this.col - 1);
      else if (b === 9) { const n = 8 - (this.col % 8); this.put(' '.repeat(n)); }
      else if (b === 7) this.bell = true;
      else if (b === 27) this.esc = 1;
      else if (b >= 32 && b < 127) this.put(String.fromCharCode(b));
    }
    this.dirty = true;
  },
  put(s) {
    const l = this.line.length < this.col ? this.line.padEnd(this.col) : this.line;
    this.line = l.slice(0, this.col) + s + l.slice(this.col + s.length);
    this.col += s.length;
  },
  flush() {
    if (!this.dirty) return;
    this.dirty = false;
    const box = this.box, atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;
    if (this.done) {
      const n = (this.done.match(/\n/g) || []).length;
      const t = document.createTextNode(this.done);
      this.out.appendChild(t); this.chunks.push([t, n]); this.lines += n;
      this.text = (this.text + this.done).slice(-200000);
      this.done = '';
      while (this.lines > 4000 && this.chunks.length > 1) { const [c, k] = this.chunks.shift(); c.remove(); this.lines -= k; }
    }
    this.lineEl.textContent = this.line;
    if (this.bell) { this.bell = false; box.classList.remove('bell'); void box.offsetWidth; box.classList.add('bell'); }
    if (atEnd) box.scrollTop = box.scrollHeight;
  },
  clear() { this.out.textContent = ''; this.chunks = []; this.lines = 0; this.text = ''; this.dirty = true; },
  all() { return this.text + this.done + this.line; },
};
term.box.addEventListener('mousedown', (e) => { if (e.button === 0) setTimeout(() => { if (!getSelection().toString()) term.input.focus({ preventScroll: true }); }); });
term.box.tabIndex = -1;
term.input.addEventListener('keydown', (e) => {
  const map = { Enter: 13, Backspace: 8, Tab: 9, Escape: 27 };
  let b = map[e.key];
  if (b === undefined && e.ctrlKey && !e.altKey && e.key.length === 1) {
    const c = e.key.toUpperCase().charCodeAt(0);
    if (c >= 64 && c <= 95) b = c - 64;     // Ctrl+C = 3 etc.
  }
  if (b !== undefined) { e.preventDefault(); sendKeys([b]); }
});
term.input.addEventListener('input', () => {
  const v = term.input.value; term.input.value = '';
  const bytes = [];
  for (const ch of v.replace(/\r?\n/g, '\r')) { const c = ch.charCodeAt(0); if (c < 128) bytes.push(c); }
  if (bytes.length) sendKeys(bytes);
});
$('clear').onclick = () => term.clear();
function sendKeys(bytes) {
  if (st.uploading) { setStatus('Typing is paused while a program uploads.', ''); return; }
  worker.postMessage({ cmd: 'key', bytes });
}

// ---------------------------------------------------------------- LEDs
const ledEls = [];
for (let i = 7; i >= 0; i--) {
  const d = document.createElement('div'); d.className = 'led'; d.innerHTML = `<i></i><span>${i}</span>`;
  d.title = 'gpio_o(' + i + ')'; $('leds').appendChild(d); ledEls[i] = d;
}
let ledShown = -1;
function showLeds(v) {
  if (v === ledShown) return;
  ledShown = v;
  for (let i = 0; i < 8; i++) ledEls[i].classList.toggle('on', !!(v >> i & 1));
  $('gpio-hex').textContent = '0x' + v.toString(16).padStart(2, '0');
}
showLeds(0);

// ---------------------------------------------------------------- worker
const worker = new Worker(new URL('sim-worker.js', import.meta.url), { type: 'module' });
let frameAcc = null, statAcc = null;
worker.onmessage = (e) => {
  const m = e.data;
  if (m.t === 'tick') {
    if (m.bytes.length) term.write(m.bytes);
    st.cycles = m.cycles; st.gpio = m.gpio; st.hz = m.hz; st.running = m.running;
    if (frameAcc) for (let i = 0; i < m.acc.length; i++) {
      if (CNT[i]) { frameAcc[i] += m.acc[i]; statAcc[i] += m.acc[i]; }
      else if (m.acc[0] > 0) { frameAcc[i] = m.acc[i]; statAcc[i] = m.acc[i]; }
    }
    if (m.up) showUpload(m.up);
  } else if (m.t === 'ready') {
    st.ready = true; st.clock = m.hz; st.names = m.names;
    CNT = m.names.map((n) => !SNAP.has(n));
    frameAcc = new Float64Array(m.names.length); statAcc = new Float64Array(m.names.length);
    resolveProbes();
    $('run').disabled = false; $('reset').disabled = false;
    for (const b of document.querySelectorAll('.progs button')) b.disabled = false;
  } else if (m.t === 'upload') {
    uploadDone(m);
  } else if (m.t === 'fatal') {
    setStatus('Simulator error: ' + m.msg, 'err');
    console.error(m.msg);
  }
};
worker.onerror = (e) => { setStatus('Could not start the simulator: ' + (e.message || 'worker error'), 'err'); };
const SNAP = new Set(['last_iaddr', 'last_daddr', 'gpio_out', 'uart_ctrl', 'mtime_lo', 'mtime_hi']);
let CNT = [];
worker.postMessage({ cmd: 'init' });

$('run').onclick = () => {
  st.running = !st.running;
  worker.postMessage({ cmd: 'run', on: st.running });
  $('run').textContent = st.running ? 'Pause' : 'Run';
};
$('reset').onclick = () => { worker.postMessage({ cmd: 'reset' }); };
$('turbo').onchange = (e) => { st.turbo = e.target.checked; worker.postMessage({ cmd: 'turbo', on: st.turbo }); };
document.addEventListener('visibilitychange', () => worker.postMessage({ cmd: 'hidden', on: document.hidden }));

// ---------------------------------------------------------------- programs + upload
let PROGS = [];
const binCache = new Map();
fetch('programs.json').then((r) => r.json()).then((list) => {
  PROGS = list;
  const ul = $('progs');
  for (const p of list) {
    const li = document.createElement('li'), b = document.createElement('button');
    b.disabled = !st.ready; b.dataset.name = p.name;
    b.innerHTML = `<span class="n"></span><span class="z"></span><span class="d"></span>`;
    b.querySelector('.n').textContent = p.name;
    b.querySelector('.z').textContent = p.bytes ? fmtBytes(p.bytes) : '';
    b.querySelector('.d').textContent = p.desc;
    b.onclick = () => loadProgram(p.name);
    li.appendChild(b); ul.appendChild(li);
  }
});
function fmtBytes(n) { return n < 1024 ? n + ' B' : (n / 1024).toFixed(1) + ' KiB'; }
async function loadProgram(name, opts = {}) {
  const p = PROGS.find((x) => x.name === name);
  if (!p) throw new Error('unknown program ' + name);
  let buf = binCache.get(name);
  if (!buf) {
    const r = await fetch(p.file);
    if (!r.ok) { setStatus('Could not fetch ' + p.file + ' (' + r.status + ')', 'err'); return; }
    buf = await r.arrayBuffer(); binCache.set(name, buf);
  }
  startUpload(name, buf, opts);
}
$('file').onchange = async (e) => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  const buf = await f.arrayBuffer();
  const err = checkExe(buf);
  if (err) { setStatus(f.name + ': ' + err, 'err'); return; }
  startUpload(f.name, buf, {});
};
// neorv32_exe.bin = 4 header words (signature, base, size, checksum) + size bytes of data
function checkExe(buf) {
  if (buf.byteLength < 20) return 'too small to be a neorv32_exe.bin';
  const v = new DataView(buf), sig = v.getUint32(0, true), base = v.getUint32(4, true), size = v.getUint32(8, true);
  if (sig !== EXE_SIG) return 'not a neorv32_exe.bin (no "NEO!" signature; build it with "make exe")';
  if (size !== buf.byteLength - 16 || size % 4) return 'header size (' + size + ') does not match the file (' + (buf.byteLength - 16) + ' data bytes)';
  if (size > IMEM_MAX) return 'program is ' + fmtBytes(size) + '; this SoC has 16 KiB of IMEM';
  if (base !== 0) return 'base address 0x' + base.toString(16) + ' is not IMEM (0x00000000)';
  let sum = 0;
  for (let i = 16; i < buf.byteLength; i += 4) sum = (sum + v.getUint32(i, true)) >>> 0;
  if (((sum + v.getUint32(12, true)) >>> 0) !== 0xffffffff) return 'checksum mismatch (corrupted file?)';
  return null;
}
function startUpload(name, buf, opts) {
  if (!st.ready || st.uploading) return;
  st.uploading = { name, t0: performance.now() };
  st.lastError = null;
  if (!st.running) { st.running = true; $('run').textContent = 'Pause'; }
  for (const b of document.querySelectorAll('.progs button')) { b.disabled = true; b.classList.toggle('cur', b.dataset.name === name); }
  $('progress').hidden = false; $('progress').firstChild.style.width = '0';
  setStatus('Resetting the SoC to upload ' + name + '…', '');
  worker.postMessage({ cmd: 'load', name, data: buf.slice(0), dropAt: opts.dropAt ?? -1 });
}
function showUpload(u) {
  $('progress').firstChild.style.width = u.pct.toFixed(1) + '%';
  setStatus(u.name + ': ' + u.msg + (u.stage === 'send' ? ' ' + u.pct.toFixed(0) + '%' : '') + '…', '');
}
function uploadDone(m) {
  const wall = st.uploading ? ((performance.now() - st.uploading.t0) / 1000).toFixed(1) : '?';
  st.uploading = null;
  for (const b of document.querySelectorAll('.progs button')) b.disabled = false;
  $('progress').hidden = true;
  if (m.state === 'done') {
    st.current = m.name;
    setStatus(m.name + ' is running (uploaded at 19200 baud: ' + (m.cycles / st.clock).toFixed(1) + ' s simulated, ' + wall + ' s here).', 'ok');
    if (m.name === 'game_of_life_64x20' || m.name === 'bus_explorer') term.input.focus({ preventScroll: true });
  } else {
    st.lastError = m.msg;
    for (const b of document.querySelectorAll('.progs button')) b.classList.remove('cur');
    setStatus('Upload of ' + m.name + ' failed: ' + m.msg + '. The SoC was reset; pick a program to try again.', 'err');
  }
}
function setStatus(s, cls) { const el = $('status'); el.textContent = s; el.className = 'status' + (cls ? ' ' + cls : ''); }

// ---------------------------------------------------------------- activity map
let MAP = null, ENT = [], PHANTOM = [];
fetch('fpa-map.json').then((r) => r.json()).then((m) => {
  MAP = m; ENT = m.entries; PHANTOM = m.phantoms;
  for (const e of ENT) e.glow = 0;
  buildStats(); resolveProbes(); attachDiagram();
});
function resolveProbes() {
  if (!MAP || !st.names.length) return;
  for (const e of ENT) {
    e.idx = e.probes.map((p) => st.names.indexOf(p));
    if (e.idx.some((i) => i < 0)) console.warn('probe missing for', e.id);
  }
}
const isPhantom = (p) => PHANTOM.some((q) => p === q || p.startsWith(q + '/'));

// level: 0 when idle; any activity shows at least 0.25, then log scale up to 1 at ~100% of cycles
function level(e, acc) {
  const cyc = acc[0];
  if (!cyc || !e.idx) return 0;
  let s = 0;
  for (const i of e.idx) if (i >= 0) s += acc[i];
  if (s <= 0) return 0;
  const r = s / cyc;
  return 0.25 + 0.75 * Math.min(1, Math.log10(1 + r * 1000) / 3);
}

// ---------------------------------------------------------------- stats widget
const statRows = new Map();
function buildStats() {
  const t = $('stats');
  for (const e of ENT.filter((x) => x.primary)) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="l"></td><td><div class="b"><i></i></div></td><td class="v">0</td>`;
    tr.firstChild.textContent = e.label; tr.title = e.what;
    t.appendChild(tr); statRows.set(e.id, tr);
  }
}
let statT = 0;
function updateStats(now) {
  if (!statAcc || now - statT < 250) return;
  statT = now;
  const a = statAcc, cyc = a[0];
  for (const e of ENT) {
    const tr = statRows.get(e.id);
    if (!tr || !e.idx) continue;
    let s = 0; for (const i of e.idx) if (i >= 0) s += a[i];
    const r = cyc ? s / cyc : 0;
    tr.querySelector('i').style.width = Math.min(100, r * 100).toFixed(1) + '%';
    tr.lastChild.textContent = cyc ? (r >= 0.1 ? r.toFixed(2) : r >= 0.001 ? r.toFixed(3) : r > 0 ? '<0.001' : '0') : '–';
  }
  const ix = (n) => st.names.indexOf(n);
  if (cyc) {
    const pc = a[ix('last_iaddr')] >>> 0, sleep = a[ix('cpu_sleep')] / cyc;
    const where = pc >= 0xffe00000 ? 'boot ROM' : pc < IMEM_MAX ? 'IMEM' : '';
    $('cpu-info').textContent = 'Last fetch (about the PC): 0x' + pc.toString(16).padStart(8, '0') + (where ? ' in ' + where : '') +
      (sleep > 0.01 ? ' · CPU asleep (wfi) ' + (sleep * 100).toFixed(0) + '% of cycles' : '');
  }
  statAcc.fill(0);
}

// ---------------------------------------------------------------- diagram hookup (same-origin iframe)
const ifr = $('fpa');
const F = { win: null, doc: null, vp: null, nodes: new Map(), level: null, want: false };
function attachDiagram() {
  if (!MAP) return;
  const d = ifr.contentDocument, w = ifr.contentWindow;
  if (!d || !d.getElementById('vp') || !w.__fpa) return;   // not loaded yet; the load event calls again
  if (F.doc === d) return;
  F.win = w; F.doc = d; F.vp = d.getElementById('vp');
  const css = d.createElement('style');
  css.textContent = `
    .demo-glow{fill:none;stroke:#f59e0b;stroke-width:9;stroke-opacity:calc(var(--a,0)*.8);vector-effect:non-scaling-stroke;pointer-events:none}
    .demo-tint{fill:#f59e0b;fill-opacity:calc(var(--a,0)*.3);stroke:none;pointer-events:none}
    .node.demo-hot>.box{stroke:#f59e0b}
    .node.demo-off{opacity:.38}
    .node.demo-off .box{stroke-dasharray:4 3}`;
  d.head.appendChild(css);
  new MutationObserver(() => { F.want = true; }).observe(F.vp, { childList: true });
  F.vp.addEventListener('click', onDiagramClick, true);
  F.vp.addEventListener('dblclick', () => clearTimeout(clickT), true);
  // theme: the viewer's own toggle (T) and this page's button stay in sync
  new MutationObserver(() => {
    const t = d.documentElement.getAttribute('data-theme');
    if (t && document.documentElement.getAttribute('data-theme') !== t) document.documentElement.setAttribute('data-theme', t);
  }).observe(d.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  const mine = document.documentElement.getAttribute('data-theme');
  if (mine) d.documentElement.setAttribute('data-theme', mine);
  F.want = true;
}
ifr.addEventListener('load', () => { F.doc = null; attachDiagram(); });

// design.html is loaded as is, with web/fpa-shim.js inserted before the viewer script so that its
// ELK layouts come from layouts.json (computed at build time) or a Web Worker; see fpa-shim.js.
const DIAG_START = '#/neorv32_top_inst', VIEWER_MARK = '<script>\n(function () {\n"use strict";';
(async function loadDiagram() {
  try {
    const [html, shim, lay] = await Promise.all([
      fetch('design.html').then((r) => r.text()), fetch('fpa-shim.js').then((r) => r.text()),
      fetch('layouts.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({}))]);
    const i = html.lastIndexOf(VIEWER_MARK);
    if (i < 0 || shim.includes('</script')) throw new Error('viewer script not found');
    window.__fpaLayouts = lay;
    const doc = html.slice(0, i) + '<script>window.__FPA_SHIM_MODE = "replay";</script>\n<script>' + shim + '</script>\n' + html.slice(i);
    ifr.src = URL.createObjectURL(new Blob([doc], { type: 'text/html' })) + DIAG_START;
  } catch (e) {
    console.warn('diagram: loading design.html directly (' + e.message + ')');
    ifr.src = 'design.html' + DIAG_START;
  }
})();

function rebuildLevel() {
  const w = F.win;
  if (!w || !w.__fpa_ready || !w.__fpa) return false;
  const parts = w.__fpa.state.path, L = parts.length ? '/' + parts.join('/') : '';
  F.nodes = new Map(); F.level = L;
  for (const g of F.vp.querySelectorAll('g.node')) {
    const id = g.getAttribute('data-id') || '';
    if (!id.startsWith('i:')) continue;
    const name = id.slice(2), full = L + '/' + name;
    const ents = ENT.filter((e) => e.fpa === full || e.fpa.startsWith(full + '/'));
    if (ents.length) {
      const boxes = g.querySelectorAll(':scope > .box'), box = boxes[boxes.length - 1];
      if (!box) continue;
      const bb = box.getBBox(), NS = 'http://www.w3.org/2000/svg';
      const mk = (cls) => {
        const r = F.doc.createElementNS(NS, 'rect');
        r.setAttribute('class', cls);
        for (const [k, v] of Object.entries({ x: bb.x, y: bb.y, width: bb.width, height: bb.height, rx: 4 })) r.setAttribute(k, v);
        return r;
      };
      const r = mk('demo-glow');
      g.insertBefore(r, g.firstChild);              // halo behind the block
      box.after(mk('demo-tint'));                   // tint over the box, under its labels
      const t = F.doc.createElementNS(NS, 'title');
      const own = ents.find((e) => e.fpa === full);
      t.textContent = (own ? own.label + ': ' + own.what : 'Live activity of ' + ents.filter((e) => e.primary).map((e) => e.label).join(', ')) +
        '. Click to show it in the simulation panel.';
      g.insertBefore(t, g.firstChild);
      F.nodes.set(name, { g, glowEl: r, ents, own, a: -1, hot: false, full });
    } else if (isPhantom(full)) {
      g.classList.add('demo-off');
      const t = F.doc.createElementNS('http://www.w3.org/2000/svg', 'title');
      t.textContent = name + ': not enabled in this configuration. fpa draws every VHDL generate branch; ' +
        'GHDL elaboration of the same RTL shows this instance does not exist with the test setup\'s generics.';
      g.insertBefore(t, g.firstChild);
    }
  }
  const lv = $('level');
  lv.textContent = 'Level: ' + (L || '/');
  if (L && isPhantom(L)) {
    const s = document.createElement('span'); s.className = 'warn';
    s.textContent = ' (this block is not enabled in this configuration)'; lv.appendChild(s);
  }
  return true;
}

let clickT = 0;
function onDiagramClick(ev) {
  const g = ev.target.closest && ev.target.closest('g.node');
  if (!g || ev.detail > 1) return;
  const id = g.getAttribute('data-id') || '', n = F.nodes.get(id.slice(2));
  if (!n) return;
  clearTimeout(clickT);
  clickT = setTimeout(() => focusWidget(n), 260);   // a double-click (open the block) cancels this
}
function focusWidget(n) {
  const e = n.own || n.ents.find((x) => x.primary) || n.ents[0];
  const card = { terminal: $('w-terminal'), leds: $('w-leds'), stats: $('w-stats') }[e.widget] || $('w-stats');
  card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  card.classList.remove('flash'); void card.offsetWidth; card.classList.add('flash');
  setTimeout(() => card.classList.remove('flash'), 1600);
  if (e.widget === 'terminal') term.input.focus({ preventScroll: true });
  if (e.widget === 'stats') {
    const ids = new Set(n.ents.filter((x) => x.primary).map((x) => x.id));
    if (!ids.size) ids.add(e.id === 'cpu_frontend' || e.id === 'cpu_lsu' || e.id === 'core_bus_switch' ? 'cpu'
      : e.id.startsWith('imem') ? 'imem' : e.id.startsWith('dmem') ? 'dmem' : e.id.startsWith('bootrom') ? 'bootrom'
      : e.id === 'io_switch' ? 'bus' : e.id.startsWith('clint') ? 'clint' : e.id);
    for (const [k, tr] of statRows) tr.classList.toggle('sel', ids.has(k));
    setTimeout(() => { for (const tr of statRows.values()) tr.classList.remove('sel'); }, 2500);
  }
  st.lastFocus = e.widget;
}

// ---------------------------------------------------------------- per-frame update
let lastT = performance.now();
function frame(now) {
  const dt = Math.min(0.25, (now - lastT) / 1000); lastT = now;
  st.frame++;
  term.flush();
  showLeds(st.gpio);
  if (F.want && rebuildLevel()) F.want = false;
  if (frameAcc && ENT.length) {
    const decay = Math.exp(-dt / 0.3);
    for (const e of ENT) e.glow = Math.max(level(e, frameAcc), e.glow * decay);
    frameAcc.fill(0);
    for (const n of F.nodes.values()) {
      if (!n.g.isConnected) continue;
      let a = 0; for (const e of n.ents) a = Math.max(a, e.glow);
      if (Math.abs(a - n.a) >= 0.02 || (a === 0 && n.a !== 0)) {
        n.a = a < 0.02 ? 0 : a;
        n.g.style.setProperty('--a', n.a.toFixed(2));
        const hot = n.a > 0.05;
        if (hot !== n.hot) { n.hot = hot; n.g.classList.toggle('demo-hot', hot); }
      }
    }
  }
  updateStats(now);
  updateSpeed(now);
  const busy = !!(F.win && F.win.__fpaLayoutPending > 0);
  if (busy !== F.busy) {
    F.busy = busy;
    $('level').textContent = busy ? 'Laying out this level in the background (large levels can take a minute)…' : 'Level: ' + (F.level ?? '');
    if (!busy) F.want = true;
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

let spT = 0;
function updateSpeed(now) {
  if (now - spT < 250 || !st.ready) return;
  spT = now;
  const el = $('speed');
  if (!st.running) el.innerHTML = '<b>paused</b>';
  else if (!st.hz) el.textContent = 'measuring…';
  else {
    const mhz = st.hz / 1e6, x = st.hz / st.clock;
    el.innerHTML = `<b>${mhz.toFixed(2)} MHz</b> · ` + (st.turbo ? `turbo, ${x.toFixed(1)}× real time`
      : x > 0.97 ? 'real time' : `slower than real time on this machine`);
  }
  const s = st.cycles / st.clock;
  $('simtime').textContent = `Simulated time ${s.toFixed(3)} s · ${Math.round(st.cycles).toLocaleString('en-US')} cycles of clk_i (SoC clock ${st.clock / 1e6} MHz)`;
}

// ---------------------------------------------------------------- theme button
$('theme').onclick = () => {
  const cur = document.documentElement.getAttribute('data-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const nx = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', nx);
  if (F.doc) F.doc.documentElement.setAttribute('data-theme', nx);
  try { localStorage.setItem('fpa-theme', nx); } catch (e) {}
};

// ---------------------------------------------------------------- test/debug hooks
window.__demo = {
  st, term, loadProgram, startUpload, checkExe,
  lit: () => [...F.nodes.entries()].filter(([, n]) => n.a > 0.05).map(([k, n]) => ({ node: 'i:' + k, path: n.full, a: n.a })),
  mapped: () => [...F.nodes.entries()].map(([k, n]) => ({ node: 'i:' + k, path: n.full, ents: n.ents.map((e) => e.id) })),
  dimmed: () => F.vp ? [...F.vp.querySelectorAll('g.node.demo-off')].map((g) => g.getAttribute('data-id')) : [],
  level: () => F.level,
  map: () => MAP,
};
