// Headless-Chrome check of the demo page over the DevTools protocol (Node >= 22: built-in WebSocket).
// usage: node check.mjs <page url> <devtools port> <user exe.bin> <out dir>
// Run through test/run.sh, which serves docs/ and starts Chrome.
import { writeFileSync } from 'node:fs';

const [url, port, userBin, outDir] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [], errors = [];
const ok = (name, pass, evidence) => { results.push({ name, pass: !!pass, evidence }); console.log((pass ? 'PASS ' : 'FAIL ') + name + ': ' + JSON.stringify(evidence)); };

const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let id = 0;
const pending = new Map();
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); return; }
  const P = m.params || {};
  if (m.method === 'Runtime.exceptionThrown') errors.push('exception: ' + (P.exceptionDetails.exception?.description || P.exceptionDetails.text));
  if (m.method === 'Runtime.consoleAPICalled' && (P.type === 'error' || P.type === 'assert')) errors.push('console.error: ' + P.args.map((a) => a.value ?? a.description).join(' '));
  if (m.method === 'Log.entryAdded' && P.entry.level === 'error') errors.push('log: ' + P.entry.text + ' ' + (P.entry.url || ''));
  if (m.method === 'Target.attachedToTarget') {           // the sim worker: watch its errors too
    const sid = P.sessionId;
    send('Runtime.enable', {}, sid); send('Log.enable', {}, sid);
  }
});
function send(method, params = {}, sessionId) {
  const i = ++id;
  ws.send(JSON.stringify(sessionId ? { id: i, method, params, sessionId } : { id: i, method, params }));
  return new Promise((res, rej) => pending.set(i, { res, rej }));
}
async function ev(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(expr + ' -> ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
  return r.result.value;
}
async function until(expr, ms, step = 100) {
  const t0 = Date.now();
  for (;;) {
    const v = await ev(expr).catch(() => null);
    if (v) return { v, ms: Date.now() - t0 };
    if (Date.now() - t0 > ms) return { v: null, ms: Date.now() - t0 };
    await sleep(step);
  }
}
async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(`${outDir}/${name}.png`, Buffer.from(r.data, 'base64'));
}
const term = `__demo.term.all()`;
const count = (s) => `(${term}.split(${JSON.stringify(s)}).length - 1)`;
const waitUpload = async (name, ms) => until(`!__demo.st.uploading && (__demo.st.current === ${JSON.stringify(name)} || __demo.st.lastError)`, ms);

await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable'); await send('DOM.enable');
await send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url });

// 1. power-on: bootloader banner and 8 s countdown
let r = await until(`window.__demo && __demo.st.ready && ${term}.includes('Auto-boot in 8s. Press any key to abort.')`, 20000);
ok('bootloader banner', r.v, { ms: r.ms, text: (await ev(term)).trim().split('\n').slice(0, 4) });

// 2. diagram: probe -> node mapping on the open level, no phantoms, glow while the bootloader runs
r = await until(`__demo.level() === '/neorv32_top_inst' && __demo.mapped().length > 5`, 20000);
const lstats = await ev(`document.getElementById('fpa').contentWindow.__fpaLayoutStats`);
ok('diagram /neorv32_top_inst shown from the layout cache', r.v && lstats && lstats.hit >= 1 && !lstats.worker,
   { ms_after_banner: r.ms, layouts: lstats });
const mapped = await ev(`__demo.mapped()`), dimmed = await ev(`__demo.dimmed()`);
await sleep(1500);
const lit = await ev(`__demo.lit()`);
ok('diagram nodes mapped (level /neorv32_top_inst)', mapped.length >= 9, { n: mapped.length, nodes: mapped.map((m) => m.node) });
ok('no phantom blocks (fpa draws what GHDL elaborates)', dimmed.length === 0, { n: dimmed.length, sample: dimmed.slice(0, 6) });
ok('glow driven by probes (bootloader running)', lit.some((l) => l.node === 'i:boot_rom_inst') && lit.some((l) => l.node === 'i:core_complex_inst'),
   lit.map((l) => l.node + '=' + l.a.toFixed(2)));
const drawn = await ev(`(() => { const d = document.getElementById('fpa').contentDocument; const has = (n) => !!d.querySelector('#vp g.node[data-id="i:' + n + '"]'); return { uart0_inst: has('uart0_inst'), gpio_inst: has('gpio_inst'), uart1_inst: has('uart1_inst'), spi_inst: has('spi_inst'), dma_inst: has('dma_inst') }; })()`);
ok('disabled peripherals not drawn', drawn && drawn.uart0_inst && drawn.gpio_inst && !drawn.uart1_inst && !drawn.spi_inst && !drawn.dma_inst, drawn);
await shot('1_boot');

// 3. speed: real time, then turbo
await sleep(2500);
const rtHz = await ev(`__demo.st.hz`);
await ev(`(document.getElementById('turbo').click(), 1)`);
await sleep(3500);
const turboHz = await ev(`__demo.st.hz`);
ok('speed readout', rtHz > 0.9e6 && turboHz > rtHz, { realtime_hz: Math.round(rtHz), turbo_hz: Math.round(turboHz), readout: await ev(`document.getElementById('speed').textContent`) });

// 4. hello_world through the bootloader
await ev(`__demo.loadProgram('hello_world')`);
r = await waitUpload('hello_world', 30000);
const helloOk = (await until(`${term}.includes('Hello world! :)')`, 15000)).v;
ok('hello_world upload + output', r.v && helloOk && !(await ev('__demo.st.lastError')), { ms: r.ms, status: await ev(`document.getElementById('status').textContent`) });
await shot('2_hello');

// 5. blink: LEDs count
await ev(`__demo.loadProgram('demo_blink_led')`);
r = await waitUpload('demo_blink_led', 30000);
const seen = new Set();
for (let i = 0; i < 30; i++) { seen.add(await ev(`__demo.st.gpio`)); await sleep(100); }
const ledDom = await ev(`[...document.querySelectorAll('.led.on')].length`);
ok('demo_blink_led: LEDs change', r.v && seen.size >= 3, { values: [...seen], leds_on_now: ledDom });
await shot('3_blink');

// 6. user upload: a .bin from outside the site, through the file input; then type into the terminal
const doc = await send('DOM.getDocument', { depth: 1 });
const inp = await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: '#file' });
await send('DOM.setFileInputFiles', { nodeId: inp.nodeId, files: [userBin] });
r = await until(`!__demo.st.uploading && /neorv32_exe\\.bin/.test(__demo.st.current || '')`, 40000);
const prompt = (await until(`${term}.includes('BUS_EXPLORER:> ')`, 10000)).v;
ok('uploaded .bin (bus_explorer) runs', r.v && prompt, { ms: r.ms, status: await ev(`document.getElementById('status').textContent`) });
await ev(`(document.getElementById('term-in').focus(), 1)`);
const enter = async () => {
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
};
await send('Input.insertText', { text: 'setup' }); await enter();
await until(`${term}.includes('selection: ')`, 5000);
await send('Input.insertText', { text: 'w' });
await until(`${count('BUS_EXPLORER:> ')} >= 2`, 5000);
await send('Input.insertText', { text: 'write fffc0004 000000a5' }); await enter();
r = await until(`__demo.st.gpio === 0xa5`, 10000);
ok('typing in the terminal reaches the UART (bus_explorer write to GPIO)', r.v, { gpio: await ev(`__demo.st.gpio`), tail: (await ev(term)).trim().split('\n').slice(-3) });
const scrolled = await ev(`(() => { const t = document.getElementById('term'); return t.scrollHeight - t.clientHeight - t.scrollTop; })()`);
ok('terminal stays scrolled to the end while typing', scrolled < 30, { px_from_end: scrolled });
await shot('4_user_bin');

// bad files are rejected before upload
writeFileSync(`${outDir}/bad.bin`, Buffer.from('this is not an executable at all'));
await send('DOM.setFileInputFiles', { nodeId: inp.nodeId, files: [`${outDir}/bad.bin`] });
r = await until(`document.getElementById('status').classList.contains('err') && document.getElementById('status').textContent`, 5000);
ok('invalid .bin rejected', r.v && /signature/.test(r.v), r.v);

// 7. timeout path: lose one byte of the upload; the page must time out, reset, and recover
const before = await ev(count('Press any key to abort.'));
await ev(`__demo.loadProgram('hello_world', { dropAt: 100 })`);
r = await until(`!__demo.st.uploading && __demo.st.lastError`, 60000);
const recovered = (await until(`${count('Press any key to abort.')} >= ${before + 2}`, 10000)).v;
ok('timeout -> error + auto reset', r.v && /timed out/.test(r.v) && recovered, { ms: r.ms, error: r.v, status: await ev(`document.getElementById('status').textContent`) });
await shot('5_timeout');
const hellos = await ev(count('Hello world! :)'));
await ev(`__demo.loadProgram('hello_world')`);
r = await waitUpload('hello_world', 30000);
const again = (await until(`${count('Hello world! :)')} > ${hellos}`, 15000)).v;
ok('next upload after the timeout works', r.v && again && !(await ev('__demo.st.lastError')), { ms: r.ms });

// 8. other levels: CPU internals glow, disabled CPU extensions not drawn
await ev(`(document.getElementById('fpa').contentWindow.__fpa.go(['neorv32_top_inst','core_complex_inst','cpu_inst']), 1)`);
await ev(`__demo.loadProgram('benchmark')`);
r = await until(`__demo.level() === '/neorv32_top_inst/core_complex_inst/cpu_inst' && __demo.mapped().length >= 2`, 20000);
await waitUpload('benchmark', 40000);
await sleep(800);
const litCpu = await ev(`__demo.lit()`), dimCpu = await ev(`__demo.dimmed()`);
const pmpDrawn = await ev(`!!document.getElementById('fpa').contentDocument.querySelector('#vp g.node[data-id="i:cpu_pmp_inst"]')`);
ok('cpu_inst level: front end + LSU glow, disabled units not drawn', litCpu.some((l) => l.node === 'i:cpu_frontend_inst') && dimCpu.length === 0 && !pmpDrawn,
   { lit: litCpu.map((l) => l.node + '=' + l.a.toFixed(2)), dimmed: dimCpu, pmp_drawn: pmpDrawn });
await shot('6_cpu_level');
r = await until(`${term}.includes('iterations/MHz')`, 30000);
const cm = (await ev(term)).split('\n').filter((l) => /Benchmark|Result|Iterations|Total ticks|Correct operation|Errors detected|CoreMark/.test(l));
ok('benchmark run completes, validated, no CoreMark naming', r.v && cm.some((l) => l.includes('Correct operation validated')) && !cm.some((l) => /CoreMark|Errors detected/.test(l)), cm);

// 9. clicking a glowing block focuses its widget
await ev(`(document.getElementById('fpa').contentWindow.__fpa.go(['neorv32_top_inst']), 1)`);
await until(`__demo.level() === '/neorv32_top_inst' && __demo.mapped().length > 5`, 20000);
const clickRes = {};
for (const [node, want] of [['uart0_inst', 'terminal'], ['gpio_inst', 'leds'], ['imem_inst', 'stats']]) {
  await ev(`(() => { const d = document.getElementById('fpa').contentDocument; const g = d.querySelector('#vp g.node[data-id="i:${node}"] .box');
    g.dispatchEvent(new d.defaultView.MouseEvent('click', { bubbles: true, detail: 1 })); return 1; })()`);
  await sleep(500);
  clickRes[node] = await ev(`__demo.st.lastFocus + (document.activeElement && document.activeElement.id ? ' / focus=' + document.activeElement.id : '')`);
  ok(`click ${node} -> ${want}`, clickRes[node].startsWith(want), clickRes[node]);
}

// 10. dark theme + narrow layout
await ev(`(document.getElementById('theme').click(), 1)`);
await sleep(600);
const th = await ev(`[document.documentElement.getAttribute('data-theme'), document.getElementById('fpa').contentDocument.documentElement.getAttribute('data-theme')]`);
ok('theme toggle syncs page + diagram', th[0] === th[1], th);
await shot('7_dark');
await send('Emulation.setDeviceMetricsOverride', { width: 420, height: 900, deviceScaleFactor: 1, mobile: true });
await sleep(1500);
const stacked = await ev(`(() => { const a = document.querySelector('.diagram').getBoundingClientRect(), b = document.querySelector('.sim').getBoundingClientRect(); return b.top >= a.bottom - 1; })()`);
ok('narrow screen stacks vertically', stacked, {});
await shot('8_narrow');

ok('no console errors', errors.length === 0, errors);
writeFileSync(`${outDir}/results.json`, JSON.stringify({ results, errors }, null, 1));
ws.close();
process.exit(results.every((x) => x.pass) ? 0 : 1);
