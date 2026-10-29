# Contributing

Thanks for helping make AI agents useful for FPGA work. Issues with a real repro are as valuable as code.

## Report a wrong or missed finding

Use the [issue form](https://github.com/al-nafisah/fpga-project-analyzer/issues/new/choose). Include the smallest project
or build log that shows it; strip anything proprietary (renaming modules and nets is fine). Don't attach the generated
`.fpa/` folder; it is rebuilt from your sources.

## Set up

Python 3.8+, standard library only. Vivado is optional.

```bash
git clone https://github.com/al-nafisah/fpga-project-analyzer && cd fpga-project-analyzer
pip install -e .                                   # or run skills/fpga-project-analyzer/scripts/fpa.py directly
fpa build examples/zynq_dma_scaler && fpa findings examples/zynq_dma_scaler
```

The example must still report the findings listed in the [README](README.md#examples) after your change.

## Where things live

| Path (under `skills/fpga-project-analyzer/scripts/fpalib/`) | What |
|---|---|
| `hdl.py` | Verilog / SystemVerilog / VHDL reader |
| `bdjson.py`, `bdtcl.py`, `hwh.py`, `xdc.py` | block designs, hardware handoff, constraints |
| `lint.py` | checks: each emits `_finding(sev, path, rule, title, detail, fix)` |
| `reports.py`, `vivado.py` | Vivado reports, logs, optional elaboration |
| `viewer.py`, `assets/viewer.html` | the diagram |
| `mcp.py`, `cli.py` | MCP server and CLI |

Agent instructions are in `skills/*/SKILL.md`.

## Pull requests

- One topic per PR; keep the tool dependency-free and offline.
- **New check:** a stable kebab-case rule id, a concrete `fix` text, and a minimal example under `examples/` that
  triggers it. Say how you confirmed it (Vivado report, simulation, or source reading).
- **New toolchain or file type:** add a small sample project under `examples/` with its expected output.

By contributing you agree your work is released under the [MIT license](LICENSE).
