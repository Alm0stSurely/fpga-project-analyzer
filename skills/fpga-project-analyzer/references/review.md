# Review checklist (AMD FPGA, Vivado/Vitis/PetaLinux 2023.2-2024.2)

Only items an agent tends to miss. Confirm each against the source before reporting.

## Clock-domain crossings
- 1-bit level signal: two flops in the destination clock, no logic between them, `ASYNC_REG` on both,
  source registered in its own clock. `xpm_cdc_single` does all of this.
  Lint `cdc-async-reg`: a recognized synchronizer (separate flops, a shift register `s <= {s[0], d}`, or one
  process) without `ASYNC_REG` in RTL attributes or XDC.
- Multi-bit: never per-bit 2-FF. Config words: `xpm_cdc_handshake` or capture with a synchronized
  strobe. Counters/pointers: `xpm_cdc_gray`. Streams: async FIFO (`xpm_fifo_async`, `axis_clock_converter`).
- Pulses: `xpm_cdc_pulse`; a fast-to-slow pulse otherwise disappears.
- Logic in front of a synchronizer glitches - register in the source domain first.
- "Quasi-static" config registers still cross: flag as low unless written only while the consumer is idle/reset.
- Constraints: `set_clock_groups -asynchronous` only after every crossing is synchronized;
  `set_max_delay -datapath_only` for gray/handshake buses. TIMING-6/7 (methodology) = unrelated clocks timed
  as related, so "timing met" proves nothing about those crossings.
- Lint clue: a net whose drivers span two domains (red dashed in the viewer).

## Resets
- One synchronized reset per clock domain (proc_sys_reset per clock, or `xpm_cdc_async_rst`): async assert,
  sync deassert.
- AXI resets are active-low (`aresetn`); `peripheral_reset` is active-high - polarity mismatches are silent.
- Interconnects take `interconnect_aresetn`; endpoints take `peripheral_aresetn`.
- A reset from another domain used asynchronously needs deassertion synchronized (lint `rst-cdc`).

## AXI / AXI-Stream
- Each interface's FREQ_HZ / CLK_DOMAIN must match the clock pin it is associated with; module references
  need X_INTERFACE_INFO/PARAMETER (ASSOCIATED_BUSIF, ASSOCIATED_RESET) when names do not match conventions.
- AXIS: TVALID must not wait for TREADY; data held stable while TVALID && !TREADY; DMA S2MM needs TLAST or it
  never completes.
- Pipeline alignment: count register stages per path. If a submodule registers data (a 1-cycle multiplier, a
  BRAM read), TVALID/TLAST/TUSER must be delayed by the same stages and the stall (TREADY) must hold them all.
- AXI DMA: buffer length width (`c_sg_length_width`, default 14 bits = 16 KiB max per transfer).
- Unassigned or overlapping address segments; masters that cannot reach a slave (Address Editor, excluded segs).
- HP/HPC ports: cache coherency only through HPC/ACP; otherwise software must flush/invalidate.

## Constraints and I/O
- Every top-level port bit needs PACKAGE_PIN and IOSTANDARD, else write_bitstream fails (NSTD-1, UCIO-1).
  PS DDR/FIXED_IO/MIO are constrained by the PS IP.
- IOSTANDARD must match the bank VCCO; differential pairs need both P and N on a pair.
- Do not `create_clock` on MMCM/PLL outputs (auto-derived); do create_clock on every external clock input.
- Synchronous external I/O needs set_input_delay/set_output_delay (TIMING-18).
- XDC on nonexistent ports is dropped with a warning ([Vivado 12-584]); check names after renaming ports.

## Timing
- WNS < 0: long paths (carry chains, wide muxes, unregistered DSP/BRAM outputs - DPIP/DPOP/REQP DRCs).
- WHS < 0 after route: clock skew, gated/derived clocks, or an unsynchronized CDC path being timed.
- check_timing no_clock / unconstrained_internal_endpoints: missing create_clock.

## HLS (Vitis HLS / Vitis Unified 2023.2+)
- `s_axilite` ports become the register map in the .hwh; `m_axi` needs `depth=` for C/RTL co-simulation.
- Compare achieved II and clock with the targets in the synthesis report; dataflow regions need streams/FIFOs
  sized for the worst burst.
- The IP runs on `ap_clk`; connect `ap_rst_n` to a reset in the same domain.

## PYNQ
- `X.bit` and `X.hwh` (or `X.xsa`) must share a basename and folder; Vivado names the bitstream after the top
  (often `<bd>_wrapper.bit`) - rename it.
- Hierarchies appear as `ol.<hier>.<ip>`; names in notebooks must match BD instance names.
- DMA buffers come from `pynq.allocate` (physically contiguous); transfer size <= the DMA length width.
- PYNQ's Interrupt class works through an `axi_intc` connected to the PS; direct IRQ_F2P wiring means polling.
- MMIO base/range must sit inside an assigned segment (lint `mmio-unmapped`).

## Bare-metal (Vitis Unified 2023.2+)
- System-device-tree drivers look up by base address: `XAxiDma_LookupConfig(XPAR_AXI_DMA_0_BASEADDR)`;
  pre-2023.2 code used `..._DEVICE_ID`.
- Flush the source buffer and invalidate the destination around DMA; align buffers to cache lines.
- Workspaces are scripted with Python (`vitis -s script.py`); XSCT is the legacy flow.

## PetaLinux / device tree
- Custom nodes and overrides: `project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi`.
- PL interrupts: Zynq-7000 IRQ_F2P[0..7] = GIC 61-68, [8..15] = 84-91; Zynq US+ pl_ps_irq0[0..7] = 121-128,
  pl_ps_irq1 = 136-143. Device tree uses `<0 (GIC-32) 4>` (the summary prints these).
- User-space access: `compatible = "generic-uio"` plus bootarg `uio_pdrv_genirq.of_id=generic-uio`, or udmabuf.
- A failed build prints "Logfile of failure stored in: ..."; that task log has the real error (`FPA logs`).
