<h1 align="center">FPGA Project Analyzer</h1>

<p align="center"><b>An AI agent skill that explains and reviews Vivado, Zynq and PYNQ projects - visually.</b><br>
Ask your agent; get a clickable Vivado-style diagram, plus the bugs that "timing met" hides.</p>

<p align="center">
<img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude_Code-plugin-d97757">
<img alt="MCP server" src="https://img.shields.io/badge/MCP-server-1d5aa6">
<img alt="Python" src="https://img.shields.io/badge/python-3.8%2B-3776ab">
<img alt="Offline" src="https://img.shields.io/badge/runs-offline-2e9d5b">
<img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue">
</p>

<p align="center"><img src="docs/how-it-works.svg" alt="How it works: your FPGA project files (Vivado .xpr/.bd/.tcl, Verilog/SystemVerilog/VHDL, .xdc/.hwh/.xsa/.bit, PYNQ notebooks, C drivers and device trees, failed build logs) go to your AI agent (Claude Code, Cursor, Codex, Gemini CLI, Copilot or any MCP/skills agent) with the fpa skill. You get a clickable diagram from block design down to registers, real bugs with file:line, why the build failed and the exact fix, and design docs. Runs offline; Vivado optional." width="100%"></p>

<p align="center"><a href="https://al-nafisah.github.io/fpga-project-analyzer/demo/neorv32/"><b>▶ Try it live</b></a>: the analyzer's diagram of a RISC-V SoC, with the same RTL running in your browser</p>

## Install

Easiest: ask your AI agent to do it.

> Install the FPGA Project Analyzer from https://github.com/al-nafisah/fpga-project-analyzer and set it up for yourself, following its README.

Or do it yourself:

1. Install the tool (Python 3.8+):

   ```
   pipx install git+https://github.com/al-nafisah/fpga-project-analyzer
   ```

2. Connect your agent:

| Agent | Setup |
|---|---|
| Claude Code | `/plugin install fpga --marketplace al-nafisah/fpga-project-analyzer` (step 1 not needed) |
| Claude Desktop | add the JSON below to its MCP config |
| Cursor | add the JSON below to `~/.cursor/mcp.json` |
| Gemini CLI | `gemini mcp add fpga fpa mcp` |
| OpenAI Codex | `codex mcp add fpga -- fpa mcp` |
| VS Code (Copilot) | add the JSON below to `.vscode/mcp.json`, with `"servers"` instead of `"mcpServers"` |

```json
{"mcpServers": {"fpga": {"command": "fpa", "args": ["mcp"]}}}
```

<sub>Any other MCP-capable agent works the same way. Agents that load `SKILL.md` skills can use [`skills/`](skills) directly.
Browser chats can't read your files; use the vendor's coding agent instead. Without AI: `fpa build <project>`, then
`fpa view <project>`. Vivado is optional.</sub>

## Use

Open your project folder in your agent and ask:

| Ask | You get |
|---|---|
| *"Explain this FPGA project"* | How the design works, as a clickable diagram |
| *"Review it for hardware bugs"* | Clock crossings, pins, resets, address map, PYNQ issues |
| *"Why did my build fail?"* | The root cause and the exact fix |

<sub>In Claude Code these are also commands: `/fpga:explain`, `/fpga:review`, `/fpga:debug`.</sub>

## See it in action

<p align="center"><img src="docs/fpga-analyzer-demo.gif" alt="Demo: block design coloured by clock domain, drill-down into RTL, ending on an unsynchronized clock-domain crossing finding" width="100%"></p>

## Features

- **Diagram:** one offline HTML file. Click from block design → hierarchy → Verilog/VHDL → registers; wires
  coloured by clock domain.
- **Checks:** clock-domain crossings traced from the block design into RTL, unconstrained pins, reset polarity,
  address map, interrupts, PYNQ `.bit`/`.hwh` mistakes.
- **Logs:** failed Vivado/PetaLinux builds condensed to the lines that matter.
- **Software links:** PYNQ notebooks, bare-metal C and device trees mapped to the blocks they drive.
- **Docs:** export any level as SVG/PNG, or generate a Markdown design document with diagrams (`fpa doc`).

## Examples

**[`examples/zynq_dma_scaler`](examples/zynq_dma_scaler)**: Vivado reports timing met; the analyzer finds

```
H io-unconstrained  gpio_rtl_0_tri_o[3]: no IOSTANDARD / PACKAGE_PIN   ← why write_bitstream failed
H cdc  .../gain_q_reg   16-bit CDC 100 MHz → 50 MHz                     (Vivado report_cdc agrees)
H cdc  .../u_mul/y_reg  CDC 50 MHz → 100 MHz through logic             (Vivado report_cdc agrees)
M pynq-bitname  notebook loads design_1.bit, build makes design_1_wrapper.bit
```

**[NEORV32 RISC-V, live in your browser](https://al-nafisah.github.io/fpga-project-analyzer/demo/neorv32/)**: the
analyzer's diagram of the unmodified [NEORV32](https://github.com/stnolting/neorv32) SoC, next to the same RTL running
in your browser (GHDL → Verilator → WebAssembly). Boot the real bootloader, run programs, and watch the blocks light
up as the CPU uses them. Sources: [`examples/neorv32`](examples/neorv32).

## Limitations

Without Vivado, RTL is read structurally: clocks routed through SystemVerilog interface internals may go
untraced, so "no findings" can mean "not checked". VHDL generics and `if`/`case ... generate` conditions are
evaluated (package constants and simple helper functions included); a condition fpa cannot evaluate keeps its
branch, a `for ... generate` is drawn once, and Verilog `generate` blocks are not evaluated. `fpa.py deep` uses
Vivado elaboration for exact results.
Findings are candidates to confirm against the source.

## Contributing

The analyzer improves with every real project it sees. Most helpful:

- **Wrong or missed finding?** [Open an issue](https://github.com/al-nafisah/fpga-project-analyzer/issues/new/choose) with a small repro or an anonymized build log.
- **A check you wish existed?** Propose it, or pick one labelled [`new-check`](https://github.com/al-nafisah/fpga-project-analyzer/labels/new-check).
- **Not on AMD?** Help add Quartus, Lattice or Yosys/nextpnr support ([`toolchain`](https://github.com/al-nafisah/fpga-project-analyzer/labels/toolchain)).
- **New here?** Start with a [`good first issue`](https://github.com/al-nafisah/fpga-project-analyzer/labels/good%20first%20issue).

See [CONTRIBUTING.md](CONTRIBUTING.md). If it saved you a debug session, a ⭐ helps other FPGA engineers find it.

---

<sub>Created by Abdullah AlNafisah with [Claude Code](https://claude.com/claude-code). Diagram layout by
[ELK](https://eclipse.dev/elk/); sketch font Architects Daughter (OFL); see [THIRD_PARTY.md](THIRD_PARTY.md). AMD, Vivado,
Zynq and PYNQ are trademarks of AMD; this project is not affiliated with AMD. [MIT](LICENSE) © 2026 Abdullah AlNafisah</sub>
