# Third-party components

| Component | Location | License |
|---|---|---|
| elkjs 0.10.0 (Eclipse Layout Kernel) | `skills/fpga-project-analyzer/scripts/fpalib/assets/vendor/elk.bundled.js` | EPL-2.0, see `ELK-LICENSE.md` next to it |
| Architects Daughter font, © 2010 Kimberly Geswein | glyph outlines in `docs/how-it-works.svg` (README sketch) | SIL Open Font License 1.1 |

## NEORV32 live demo (`examples/neorv32/`, `docs/demo/neorv32/`)

The demo site is built from upstream sources by `examples/neorv32/build.sh`; no third-party source code is vendored
in this repository except where noted. The built files in `docs/demo/neorv32/` carry these components (details
in `docs/demo/neorv32/THIRD_PARTY.txt`):

| Component | Where it ends up | License |
|---|---|---|
| [NEORV32](https://github.com/stnolting/neorv32) v1.13.7 RTL, bootloader image, software library and example programs, © Stephan Nolting and NEORV32 contributors | `neorv32_sim.wasm` (RTL + boot ROM), `programs/*.bin`; the diagram in `design.html` is fpa's output for the unmodified RTL | BSD-3-Clause |
| [CoreMark](https://github.com/eembc/coremark) (EEMBC) with the [neorv32-coremark](https://github.com/stnolting/neorv32-coremark) port | `programs/benchmark.bin`, a modified derivative (1 iteration, sized for 16 KiB, renamed output); its results are not CoreMark scores (CoreMark is an EEMBC trademark) | Apache-2.0 |
| `examples/neorv32/sw/ee_printf_neorv32.c` | small printf replacement written for this demo, compiled into the benchmark program | MIT (this repository) |
| [Verilator](https://verilator.org) runtime (`verilated*.cpp`) | compiled into `neorv32_sim.wasm` | LGPL-3.0-only or Artistic-2.0 |
| [Emscripten](https://emscripten.org) runtime and libc | `neorv32_sim.js` / `neorv32_sim.wasm` | MIT / University of Illinois NCSA |
| [Arty A7 constraints](https://github.com/stnolting/neorv32-setups) (`arty_a7_test_setup.xdc`, neorv32-setups @57f86d5) | read by fpa; only reflected in `design.html` | BSD-3-Clause |

The page uses no third-party JavaScript libraries (the terminal is a small built-in one).
