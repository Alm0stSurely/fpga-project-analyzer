// NEORV32 demo SoC - C API of the Verilated model, for JS (WebAssembly) and native.
// ---------------------------------------------------------------------------
// Every function is extern "C". In the wasm build they are exported with
// EMSCRIPTEN_KEEPALIVE, so JS calls them as Module._neo_xxx(...).
//
// JS note: wasm returns uint32_t as a signed i32 number, so values >= 2^31
// (e.g. neo_probe(NEO_P_LAST_IADDR) = 0xffe0xxxx) need ">>> 0" in JS. Reading the
// counters through a Uint32Array view on neo_probes() avoids this. neo_cycles()
// returns a double, which avoids BigInt.
//
// Clocking: one "cycle" = one rising edge of clk_i (two eval() calls).
// Nothing runs between neo_step() calls, so JS owns the pacing. Typical use
// is one neo_step(N) per animation frame (or per worker tick), with
// N = target_hz / fps.
//
// UART: the model's uart0_txd_o is decoded 8N1 inside the C++ step loop into a
// 64 KiB TX ring (SoC -> host). Host -> SoC bytes are queued and shifted into
// uart0_rxd_i 8N1 with one extra idle bit between frames, which the bootloader's
// 1-entry RX FIFO needs. The bit period follows the live UART0 CTRL register
// (prsc/baud). Until the SoC enables UART0, the bootloader default
// CLK/(2*19200)*2 is used.
//
// Activity probes: internal netlist signals made readable by probes.vlt
// (Verilator public_flat_rd) are sampled once per cycle after the rising edge.
// The counters cover the most recent neo_step() call and are cleared when the
// next one starts.
// ---------------------------------------------------------------------------
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// ---- lifecycle ----
int         neo_init(void);         // power-on: (re)create the model (all RAM/regs zero), rstn_i low 16 cycles; cycle counter -> 0
void        neo_reset(void);        // warm reset (reset button): rstn_i low 16 cycles, IMEM/DMEM keep contents; UART queues cleared
uint32_t    neo_step(uint32_t n);   // run n clk cycles; returns cycles actually run (< n only after $finish)
double      neo_cycles(void);       // clk cycles since neo_init (double: exact up to 2^53)
int         neo_finished(void);     // 1 if the model executed $finish
uint32_t    neo_clock_hz(void);     // CLOCK_FREQUENCY generic the Verilog was converted with (virtual Hz)
const char* neo_build_info(void);   // human-readable build string

// ---- UART0 (SoC TX -> host) ----
int         neo_uart_getc(void);                         // next received byte, or -1 if none
uint32_t    neo_uart_tx_avail(void);                     // bytes waiting in the TX ring
uint32_t    neo_uart_read(uint8_t* dst, uint32_t max);   // bulk read, returns count
uint32_t    neo_uart_tx_dropped(void);                   // bytes lost to ring overflow (JS drained too slowly)
// ---- UART0 (host -> SoC RX) ----
void        neo_uart_putc(uint32_t byte);                // enqueue one byte for uart0_rxd_i
uint32_t    neo_uart_write(const uint8_t* src, uint32_t n); // enqueue n bytes (e.g. a whole neorv32_exe.bin)
uint32_t    neo_uart_rx_pending(void);                   // bytes not yet fully shifted in (queued + in flight)
uint32_t    neo_uart_bit_cycles(void);                   // current UART bit period in clk cycles
uint8_t*    neo_buf(void);                               // 64 KiB scratch buffer for JS <-> wasm byte transfers
uint32_t    neo_buf_size(void);

// ---- pins ----
uint32_t    neo_gpio(void);         // gpio_o[7:0]
uint32_t    neo_uart_txd(void);     // uart0_txd_o pin level

// ---- activity probes (counters for the most recent neo_step) ----
const uint32_t* neo_probes(void);       // pointer to NEO_P_COUNT uint32 (index = enum below)
uint32_t    neo_probe(uint32_t idx);    // single counter
uint32_t    neo_probe_count(void);      // NEO_P_COUNT
const char* neo_probe_names(void);      // comma-separated names, in index order
uint32_t    neo_activity(void);         // bitmask NEO_A_* of blocks active during the last step
const char* neo_activity_names(void);   // comma-separated names, bit 0 first
void        neo_set_probes(int on);     // 0 = skip per-cycle sampling (speed reference); default 1

#ifdef __cplusplus
}
#endif

// Probe counter indices (keep in sync with NEO_PROBE_NAMES in the .cpp)
enum {
  NEO_P_CYCLES = 0,     // cycles covered by this window
  NEO_P_CPU_IFETCH,     // CPU instruction-fetch requests (ibus stb)
  NEO_P_CPU_DACC,       // CPU load/store requests (dbus stb)
  NEO_P_CPU_DWR,        // ... of which stores
  NEO_P_CPU_SLEEP,      // cycles with cpu sleep_o = 1 (WFI)
  NEO_P_IMEM,           // IMEM requests
  NEO_P_IMEM_WR,        // ... of which writes
  NEO_P_DMEM,           // DMEM requests
  NEO_P_DMEM_WR,        // ... of which writes
  NEO_P_BOOTROM,        // boot ROM requests
  NEO_P_UART0,          // UART0 register accesses (bus stb)
  NEO_P_GPIO,           // GPIO register accesses
  NEO_P_CLINT,          // CLINT register accesses
  NEO_P_SYSINFO,        // SYSINFO register accesses
  NEO_P_UART_TX_BUSY,   // cycles the UART0 TX engine is shifting
  NEO_P_UART_RX_BUSY,   // cycles the UART0 RX engine is shifting
  NEO_P_MTI,            // cycles with the CLINT timer interrupt pending
  NEO_P_LAST_IADDR,     // last instruction-fetch address (~PC)
  NEO_P_LAST_DADDR,     // last load/store address
  NEO_P_GPIO_OUT,       // gpio_o at the end of the window
  NEO_P_GPIO_TOGGLES,   // number of gpio_o changes in the window
  NEO_P_UART_CTRL,      // UART0 CTRL register (enable[0] prsc[5:3] baud[15:6])
  NEO_P_MTIME_LO,       // CLINT mtime[31:0] at the end of the window
  NEO_P_MTIME_HI,       // CLINT mtime[63:32]
  NEO_P_UART_TX_BYTES,  // bytes decoded from uart0_txd_o in the window
  NEO_P_UART_RX_BYTES,  // bytes fully shifted into uart0_rxd_i in the window
  NEO_P_COUNT
};

// Activity bits returned by neo_activity() (diagram blocks)
enum {
  NEO_A_CPU      = 1u << 0,  // any ifetch or load/store
  NEO_A_IMEM     = 1u << 1,
  NEO_A_DMEM     = 1u << 2,
  NEO_A_BOOTROM  = 1u << 3,
  NEO_A_UART0    = 1u << 4,  // UART0 register access (bootloader polls this constantly)
  NEO_A_GPIO     = 1u << 5,  // GPIO register access
  NEO_A_CLINT    = 1u << 6,
  NEO_A_SYSINFO  = 1u << 7,
  NEO_A_UART_LINE = 1u << 8, // UART0 TX or RX engine shifting (real serial traffic)
  NEO_A_GPIO_PIN = 1u << 9,  // gpio_o changed
  NEO_A_MTI      = 1u << 10, // timer interrupt pending
  NEO_A_SLEEP    = 1u << 11, // CPU asleep for at least one cycle
  NEO_A_MEM_WR   = 1u << 12  // IMEM or DMEM write (e.g. program upload)
};
