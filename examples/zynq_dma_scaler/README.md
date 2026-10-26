# Demo: PYNQ-Z2 DMA + gain stage

Zynq-7000 (xc7z020) Block Design: PS7 → AXI DMA → `stream_proc` (RTL module reference: Verilog + VHDL)
→ DMA, an AXI GPIO for LEDs and the gain word, and a notebook plus bare-metal C that drive it.
Three bugs were planted; Vivado still reports timing met. A fourth was not planted: an agent reviewing the
project with this skill found it while reading the RTL the analyzer pointed it to.

| Bug | Where | Found by |
|---|---|---|
| LED 3 has no pin constraint → `write_bitstream` fails (NSTD-1, UCIO-1) | `constraints/pynq_z2.xdc` | checks |
| Gain word crosses 100 → 50 MHz unsynchronized | `rtl/stream_scaler.v:19` | checks (Vivado `report_cdc` agrees) |
| ...and back 50 → 100 MHz through the multiplier | `rtl/sat_mul.vhd` | checks (Vivado `report_cdc` agrees) |
| Notebook loads `design_1.bit`; Vivado writes `design_1_wrapper.bit` | `notebooks/scaler_demo.ipynb` | checks |
| `sat_mul` registers `y`, but `valid`/`last` are not delayed → output[i] = f(input[i-1]) | `rtl/stream_scaler.v:30-37` | agent review |

```bash
FPA="python3 ../../skills/fpga-project-analyzer/scripts/fpa.py"
$FPA build .                                   # no Vivado needed: uses bd/, rtl/, expected/
$FPA view . --overlay overlay.example.json     # explanation notes + flows as an agent would write them
$FPA logs expected/impl_runme.log              # the failed bitstream run, condensed
```

`vivado -mode batch -source build.tcl -tclargs impl` rebuilds the project (Vivado 2022.2+), refreshes `bd/`
and reproduces the failed run under `vivado/`.
