// NEORV32 demo: runs the Verilated SoC (WebAssembly) off the main thread.
// Pacing: real time = CLOCK_FREQUENCY cycles per wall-clock second (1 MHz), or Turbo
// (as fast as this machine goes). The bootloader upload protocol runs here, cycle-exact
// between steps, so it does not depend on the page's frame rate.
import createNeorv32 from './neorv32_sim.js';

const CHUNK = 4000;          // cycles per neo_step: about 2 ms of work
const SLICE_MS = 14;         // max work per slice before yielding to messages
const TICK_MS = 16;          // UI update period
let M = null, HZ = 1e6, NAMES = [], NP = 0, view = null;
let running = true, turbo = false, hidden = false;
let rt = { t: 0, c: 0 };     // real-time base: wall ms <-> cycles
let acc = null, out = [], lastTick = 0, spd = { t: 0, c: 0, hz: 0 };
let up = null;               // upload state machine, see load()
const CNT = new Set(['cycles', 'cpu_ifetch', 'cpu_dacc', 'cpu_dwr', 'cpu_sleep', 'imem', 'imem_wr', 'dmem', 'dmem_wr',
  'bootrom', 'uart0', 'gpio', 'clint', 'sysinfo', 'uart_tx_busy', 'uart_rx_busy', 'mti', 'gpio_toggles',
  'uart_tx_bytes', 'uart_rx_bytes']);
let isCnt = [];

const post = (m, tr) => self.postMessage(m, tr || []);
const cyc = () => M._neo_cycles();
const yieldNow = (() => { const ch = new MessageChannel(); ch.port1.onmessage = () => slice(); return () => ch.port2.postMessage(0); })();
let pending = false;          // one slice scheduled at a time
function schedule(ms) {
  if (pending) return;
  pending = true;
  if (ms > 0) setTimeout(slice, ms); else yieldNow();
}

function probes() {
  if (!view || view.buffer !== M.HEAPU8.buffer) view = new Uint32Array(M.HEAPU8.buffer, M._neo_probes(), NP);
  return view;
}
function step(n) {
  M._neo_step(n);
  const p = probes();
  for (let i = 0; i < NP; i++) acc[i] = isCnt[i] ? acc[i] + p[i] : p[i];
  let k;
  const buf = M._neo_buf();
  while ((k = M._neo_uart_read(buf, 4096)) > 0) {
    const b = M.HEAPU8.slice(buf, buf + k);
    out.push(b);
    if (up && up.ut.length < 65536) for (let i = 0; i < k; i++) up.ut += String.fromCharCode(b[i]);
  }
  if (up) upload();
}

function slice() {
  pending = false;
  if (!M || !running || hidden) { tick(true); return; }
  const now = performance.now();
  let budget = Infinity;
  if (!turbo) {
    const behind = rt.c + (now - rt.t) * (HZ / 1000) - cyc();
    if (behind > HZ * 0.1) { rt = { t: now, c: cyc() }; budget = 0; } // can't keep up: drop the backlog
    else budget = behind;
  }
  const end = now + SLICE_MS;
  while (budget >= CHUNK / 4 && performance.now() < end) {
    const n = Math.min(CHUNK, Math.floor(budget));
    step(n);
    budget -= n;
    if (!running) break;
  }
  tick(false);
  if (turbo || budget >= CHUNK / 4) schedule(0); else schedule(4);
}

function tick(force) {
  const now = performance.now();
  if (!force && now - lastTick < TICK_MS) return;
  lastTick = now;
  if (!M) return;
  if (now - spd.t >= 500) {
    const c = cyc();
    spd.hz = spd.t && running && !hidden ? (c - spd.c) / ((now - spd.t) / 1000) : 0;
    spd.t = now; spd.c = c;
  }
  let n = 0;
  for (const b of out) n += b.length;
  const bytes = new Uint8Array(n);
  n = 0;
  for (const b of out) { bytes.set(b, n); n += b.length; }
  out = [];
  const a = acc; acc = new Float64Array(NP);
  post({ t: 'tick', cycles: cyc(), gpio: M._neo_gpio(), bytes, acc: a, hz: spd.hz, running, turbo,
         rxPending: M._neo_uart_rx_pending(), up: up && upStatus() }, [bytes.buffer, a.buffer]);
}

// ---------------------------------------------------------------- bootloader upload
// Verified protocol (19200 8N1, 1-entry RX FIFO): reset -> any key at "Press any key" ->
// 'u' -> exe bytes (the C API paces them: 11 bit times = 572 cycles each) -> "OK" -> 'e'.
// Timeouts are in simulated cycles. A lost byte makes the bootloader wait forever, so a
// timeout (or any ERROR_*) resets the SoC and reports an error.
const STAGES = {
  banner: { want: 'Press any key to abort.', budget: 1.5e6, msg: 'waiting for the bootloader' },
  cmd1:   { want: 'CMD:> ', budget: 1e6, msg: 'stopping the auto-boot' },
  await:  { want: 'Awaiting neorv32_exe.bin', budget: 1e6, msg: "sending 'u'" },
  send:   { want: 'OK', budget: 0, msg: 'uploading' },
  cmd2:   { want: 'CMD:> ', budget: 1e6, msg: 'checking' },
  boot:   { want: 'Booting', budget: 1e6, msg: "starting it with 'e'" },
};
function load(name, data, dropAt) {
  const bytes = new Uint8Array(data);
  if (dropAt >= 0 && dropAt < bytes.length) bytes.copyWithin(dropAt, dropAt + 1); // test hook: lose one byte
  up = { name, bytes, n: dropAt >= 0 ? bytes.length - 1 : bytes.length, t0: cyc(), ut: '', pos: 0 };
  running = true;
  M._neo_reset();
  out.push(new TextEncoder().encode('\r\n[reset: loading ' + name + ']\r\n'));
  enter('banner');
}
function enter(stage) {
  up.stage = stage;
  up.since = cyc();
  up.budget = stage === 'send' ? up.n * 11 * M._neo_uart_bit_cycles() * 1.5 + 2e6 : STAGES[stage].budget;
}
function upload() {
  const e = /ERROR_[A-Z]+/.exec(up.ut);
  if (e) return fail('the bootloader reported ' + e[0]);
  for (;;) {
    const want = STAGES[up.stage].want, i = up.ut.indexOf(want, up.pos);
    if (i < 0) break;
    up.pos = i + want.length;
    switch (up.stage) {
      case 'banner': M._neo_uart_putc(32); enter('cmd1'); break;     // any key
      case 'cmd1': M._neo_uart_putc(117); enter('await'); break;     // 'u', no CR/LF
      case 'await': {
        const buf = M._neo_buf();
        M.HEAPU8.set(up.bytes.subarray(0, up.n), buf);
        M._neo_uart_write(buf, up.n);
        enter('send');
        break;
      }
      case 'send': enter('cmd2'); break;
      case 'cmd2': M._neo_uart_putc(101); enter('boot'); break;      // 'e'
      case 'boot': {
        const name = up.name, c = cyc() - up.t0;
        up = null;
        post({ t: 'upload', state: 'done', name, cycles: c });
        return;
      }
    }
  }
  if (cyc() - up.since > up.budget) {
    const st = up.stage;
    fail('timed out ' + (st === 'send' ? 'waiting for "OK" after the upload (a byte was probably lost)'
                                     : 'while ' + STAGES[st].msg + ' (no "' + STAGES[st].want.trim() + '")'));
  }
}
function upStatus() {
  const s = up.stage;
  const pct = s === 'send' ? 100 * (1 - M._neo_uart_rx_pending() / up.n) : (s === 'cmd2' || s === 'boot' ? 100 : 0);
  return { name: up.name, stage: s, msg: STAGES[s].msg, pct };
}
function fail(why) {
  const name = up.name, stage = up.stage;
  up = null;
  M._neo_reset();               // a stuck bootloader only recovers by reset
  out.push(new TextEncoder().encode('\r\n[upload failed: ' + why + '; SoC reset]\r\n'));
  post({ t: 'upload', state: 'error', name, stage, msg: why });
}

// ---------------------------------------------------------------- messages
self.onmessage = async (e) => {
  const m = e.data;
  try {
    switch (m.cmd) {
      case 'init': {
        M = await createNeorv32({ locateFile: (f) => new URL(f, import.meta.url).href });
        HZ = M._neo_clock_hz() >>> 0;
        NAMES = M.UTF8ToString(M._neo_probe_names()).split(',');
        NP = M._neo_probe_count();
        isCnt = NAMES.map((n) => CNT.has(n));
        acc = new Float64Array(NP);
        M._neo_init();
        rt = { t: performance.now(), c: 0 };
        post({ t: 'ready', hz: HZ, names: NAMES, build: M.UTF8ToString(M._neo_build_info()) });
        schedule(0);
        break;
      }
      case 'run': running = !!m.on; rt = { t: performance.now(), c: cyc() }; spd.t = 0; schedule(0); break;
      case 'turbo': turbo = !!m.on; rt = { t: performance.now(), c: cyc() }; spd.t = 0; schedule(0); break;
      case 'hidden': hidden = !!m.on; rt = { t: performance.now(), c: cyc() }; spd.t = 0; schedule(0); break;
      case 'reset': {
        if (up) { const n = up.name; up = null; post({ t: 'upload', state: 'error', name: n, msg: 'cancelled by reset' }); }
        M._neo_reset();
        out.push(new TextEncoder().encode('\r\n[reset]\r\n'));
        rt = { t: performance.now(), c: cyc() }; schedule(0);
        break;
      }
      case 'key': if (!up) for (const b of m.bytes) M._neo_uart_putc(b); break;
      case 'load': load(m.name, m.data, m.dropAt ?? -1); rt = { t: performance.now(), c: cyc() }; schedule(0); break;
    }
  } catch (err) {
    post({ t: 'fatal', msg: String(err && err.stack || err) });
  }
};
