# NEORV32 live demo

Source of https://al-nafisah.github.io/fpga-project-analyzer/demo/neorv32/. The page puts fpa's diagram of the
unmodified [NEORV32](https://github.com/stnolting/neorv32) v1.13.7 RTL (`neorv32_test_setup_bootloader` with the
Arty A7 XDC) next to the same RTL simulated in the browser. The simulation path is
GHDL `synth` → Verilog → Verilator → em++ → WebAssembly, running in a Web Worker at a real-time 1 MHz.
The built site lives in `docs/demo/neorv32/`. GitHub Pages serves `docs/` from `main`.

## Rebuild

```sh
bash examples/neorv32/build.sh          # about 3 min; writes docs/demo/neorv32/
bash examples/neorv32/test/run.sh       # serves docs/ and checks the page in headless Chrome
```

The build needs Verilator 5.052, Python 3, Node ≥ 22 and Chrome. GHDL 6.0.0 (mcode), xPack RISC-V GCC 15.2.0-1
and emsdk 6.0.13 are taken from `$TOOLS` (default `~/.cache/neorv32-demo/tools`); if one is missing, the build
downloads it and checks its sha256. The pinned sources go to `$SRC` (default `~/.cache/neorv32-demo/src`):

- neorv32 v1.13.7
- neorv32-setups @57f86d5, for the XDC only
- neorv32-coremark @e1553f1

Intermediate files go to `$WORK` (default `~/.cache/neorv32-demo/demo-build`). The header of `build.sh` lists all
the variables. Rebuilding from the same tools and sources gives the same `neorv32_sim.wasm` and programs, byte for byte.

## Files

| Path | What it is |
|---|---|
| `build.sh` | The whole pipeline: sources → Verilog → wasm, programs, fpa diagram, checked map, ELK layouts, site |
| `rtl/neorv32_demo_wrapper.vhd` | A pass-through wrapper around the unmodified test setup. It sets only `CLOCK_FREQUENCY` = 1 MHz, which changes no hardware, only the SYSINFO clock value the software reads |
| `sim/probes.vlt`, `sim/probes.h` | Verilator `public_flat_rd` access to internal bus strobes, used as activity probes. They add no ports |
| `sim/neorv32_sim_api.{h,cpp}` | C API that JS calls: step, UART 8N1 encode/decode, GPIO, probe counters |
| `sim/vl_wasm_stubs.cpp` | Stubs for three libc symbols that the Verilator runtime references but never calls |
| `sw/ee_printf_neorv32.c` | Minimal printf, so the CoreMark-derived benchmark fits in 16 KiB of IMEM |
| `web/` | The page: `index.html`, `app.js` (UI, diagram hookup), `sim-worker.js` (sim + bootloader upload), `fpa-shim.js` (layout cache), `style.css`, `programs.json`, `activity-map.json` |
| `tools/fpa_map.py` | Checks every probe → diagram-node entry against `design.html` and GHDL's elaborated tree. Writes `fpa-map.json` with the phantom blocks |
| `tools/record_layouts.mjs`, `tools/inject_shim.py` | Precompute fpa's ELK layouts for every level that exists in this configuration |
| `test/run.sh`, `test/check.mjs` | Headless-Chrome check over the DevTools protocol |

## How the page works

- **Simulation.** `sim-worker.js` steps the model in 4000-cycle chunks, paced to 1 M cycles/s or as fast as
  possible (Turbo). Picking a program runs the bootloader's upload protocol inside the worker:
  1. Reset.
  2. Send a key at `Press any key`.
  3. Send `u`.
  4. Send the exe bytes, paced to 11 bit times each, which the 1-entry RX FIFO needs.
  5. Wait for `OK`.
  6. Send `e`.

  Each step has a time limit in simulated cycles. On a timeout or an `ERROR_*`, the worker resets the SoC and
  reports the error, because a bootloader that lost a byte waits forever.
- **Activity highlight.** `activity-map.json` is the explicit table that maps each probe to an fpa node path.
  On every animation frame, the page turns the probe counters gathered since the last frame into a glow level
  for each block. It applies the glow to the matching node at the open hierarchy level, or to that node's
  ancestor if the block itself isn't shown there.
- **Phantom blocks.** fpa evaluates generics and VHDL generate conditions, so it draws the same 34 RTL instances
  that GHDL elaborates. As a safety net, any block fpa draws that GHDL does not elaborate (a branch fpa could not
  decide) is dimmed and gets a tooltip. `fpa_map.py` reports the count; with v1.13.7 it is 0.
- **Click to focus.** Clicking a glowing block focuses its widget: UART goes to the terminal, GPIO to the LEDs,
  and the rest to the activity table.
- **Diagram and layout cache.** `design.html` is fpa's output, unchanged except for one scrubbed metadata field
  (`meta.root`, the local build path). In the browser, `app.js` inserts `fpa-shim.js` before the viewer script.
  The shim answers ELK layout requests from `layouts.json`. At build time, laying out the 37-block `neorv32_top`
  level takes about 70 s on the main thread. Requests the cache cannot answer go to a Web Worker.
