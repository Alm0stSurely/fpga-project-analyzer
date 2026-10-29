// Activity probes: direct reads of internal netlist signals of the Verilated
// NEORV32 demo SoC. Every signal here is made readable by probes.vlt
// (Verilator public_flat_rd) - the VHDL wrapper itself has no extra ports.
//
// Names are <instance path>__DOT__<signal>; GHDL record ports such as
// "\bus_req_i[stb] " are encoded by Verilator as bus_req_i__05bstb__05d
// ("__05b" = '[', "__05d" = ']').
#pragma once
#include "Vneorv32_demo_wrapper.h"
#include "Vneorv32_demo_wrapper___024root.h"

#define NEO_TOP_  neorv32_demo_wrapper__DOT__test_setup_inst__DOT__neorv32_top_inst__DOT__
#define NEO_CAT2_(a, b) a##b
#define NEO_CAT_(a, b) NEO_CAT2_(a, b)
#define NEO_SIG(path) NEO_CAT_(NEO_TOP_, path)

// ---- CPU (neorv32_cpu ports, core_complex_gen(1).core_complex_inst.cpu_inst) ----
#define P_CPU_IBUS_STB(r)  ((r)->NEO_SIG(core_complex_gen_n1_core_complex_inst__DOT__cpu_inst__DOT__ibus_req_o__05bstb__05d))
#define P_CPU_IBUS_ADDR(r) ((r)->NEO_SIG(core_complex_gen_n1_core_complex_inst__DOT__cpu_inst__DOT__ibus_req_o__05baddr__05d))
#define P_CPU_DBUS_STB(r)  ((r)->NEO_SIG(core_complex_gen_n1_core_complex_inst__DOT__cpu_inst__DOT__dbus_req_o__05bstb__05d))
#define P_CPU_DBUS_RW(r)   ((r)->NEO_SIG(core_complex_gen_n1_core_complex_inst__DOT__cpu_inst__DOT__dbus_req_o__05brw__05d))
#define P_CPU_DBUS_ADDR(r) ((r)->NEO_SIG(core_complex_gen_n1_core_complex_inst__DOT__cpu_inst__DOT__dbus_req_o__05baddr__05d))
#define P_CPU_SLEEP(r)     ((r)->NEO_SIG(core_complex_gen_n1_core_complex_inst__DOT__cpu_inst__DOT__sleep_o))

// ---- memories ----
#define P_IMEM_STB(r)    ((r)->NEO_SIG(memory_system_imem_enabled_imem_inst__DOT__req_stb_i))
#define P_IMEM_RW(r)     ((r)->NEO_SIG(memory_system_imem_enabled_imem_inst__DOT__req_rw_i))
#define P_DMEM_STB(r)    ((r)->NEO_SIG(memory_system_dmem_enabled_dmem_inst__DOT__req_stb_i))
#define P_DMEM_RW(r)     ((r)->NEO_SIG(memory_system_dmem_enabled_dmem_inst__DOT__req_rw_i))
#define P_BOOTROM_STB(r) ((r)->NEO_SIG(io_system_bootrom_enabled_boot_rom_inst__DOT__req_stb_i))

// ---- IO devices: per-device bus select (request strobe) ----
#define P_UART0_STB(r)   ((r)->NEO_SIG(io_system_uart0_enabled_uart0_inst__DOT__bus_req_i__05bstb__05d))
#define P_GPIO_STB(r)    ((r)->NEO_SIG(io_system_gpio_enabled_gpio_inst__DOT__bus_req_i__05bstb__05d))
#define P_CLINT_STB(r)   ((r)->NEO_SIG(io_system_clint_enabled_clint_inst__DOT__bus_req_i__05bstb__05d))
#define P_SYSINFO_STB(r) ((r)->NEO_SIG(io_system_sysinfo_inst__DOT__bus_req_i__05bstb__05d))

// ---- UART0 internals (GHDL flattens records LSB-first, first field at bit 0) ----
// ctrl_t: enable[0] sim_mode[1] hwfc_en[2] prsc[5:3] baud[15:6] irq_*[19:16]
// serial_engine_t (tx, rx): state[1:0] sreg[10:2] bitcnt[14:11] baudcnt[24:15] sync[27:25] done[28]
#define P_UART0_CTRL(r)  ((r)->NEO_SIG(io_system_uart0_enabled_uart0_inst__DOT__ctrl))
#define P_UART0_TX(r)    ((r)->NEO_SIG(io_system_uart0_enabled_uart0_inst__DOT__tx))
#define P_UART0_RX(r)    ((r)->NEO_SIG(io_system_uart0_enabled_uart0_inst__DOT__rx))
#define UART_ENGINE_BUSY(e) (((e) & 3u) == 3u) // state = "11" -> shifting a frame

// ---- CLINT ----
#define P_CLINT_MTIME(r) ((r)->NEO_SIG(io_system_clint_enabled_clint_inst__DOT__mtime))
#define P_CLINT_MTI(r)   ((r)->NEO_SIG(io_system_clint_enabled_clint_inst__DOT__mti_o))

// UART0 bit period in clk_i cycles, from the live control register.
// clkgen taps: 0:/2 1:/4 2:/8 3:/64 4:/128 5:/1024 6:/2048 7:/4096
static inline unsigned uart_bit_cycles_from_ctrl(uint32_t ctrl) {
  static const unsigned div[8] = {2, 4, 8, 64, 128, 1024, 2048, 4096};
  unsigned prsc = (ctrl >> 3) & 7u, baud = (ctrl >> 6) & 0x3ffu;
  return div[prsc] * (baud + 1u);
}
