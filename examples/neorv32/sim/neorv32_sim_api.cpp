// NEORV32 demo SoC - C API around the Verilated model (see neorv32_sim_api.h).
// ---------------------------------------------------------------------------
// The UART decoder/driver and the probe sampling follow the native Verilator
// harness used during development, with the same timing rules, so the same
// input schedule gives the same cycle stamps natively and in wasm. Only the
// I/O plumbing differs: queues instead of stdin/stdout.
// ---------------------------------------------------------------------------
#include "neorv32_sim_api.h"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>

#include "verilated.h"
#include "probes.h" // Vneorv32_demo_wrapper + P_* accessors (public_flat_rd via probes.vlt)

#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#include <emscripten/version.h>
#define API extern "C" EMSCRIPTEN_KEEPALIVE
#else
#define API extern "C"
#endif

#ifndef CLOCK_FREQUENCY
#define CLOCK_FREQUENCY 1000000 // must match the -gCLOCK_FREQUENCY used for the GHDL conversion
#endif
#define STR2_(x) #x
#define STR_(x) STR2_(x)

static const char NEO_PROBE_NAMES[] =
  "cycles,cpu_ifetch,cpu_dacc,cpu_dwr,cpu_sleep,imem,imem_wr,dmem,dmem_wr,bootrom,"
  "uart0,gpio,clint,sysinfo,uart_tx_busy,uart_rx_busy,mti,last_iaddr,last_daddr,"
  "gpio_out,gpio_toggles,uart_ctrl,mtime_lo,mtime_hi,uart_tx_bytes,uart_rx_bytes";
static const char NEO_ACTIVITY_NAMES[] =
  "cpu,imem,dmem,bootrom,uart0,gpio,clint,sysinfo,uart_line,gpio_pin,mti,sleep,mem_wr";

static const unsigned RESET_CYCLES = 16;

// ---------------- UART receiver (decodes uart0_txd_o), as in the native harness ----------------
struct UartDecoder {
  bool in_frame = false;
  int prev = 1, nbit = 0;
  uint8_t data = 0;
  uint64_t next_sample = 0;
  unsigned bitc = 0;
  uint64_t frames = 0, framing_errors = 0;
  inline int step(int line, uint64_t cyc, unsigned bit_cycles) {
    int r = -1;
    if (!in_frame) {
      if (prev == 1 && line == 0) { // start bit edge
        in_frame = true; nbit = 0; data = 0; bitc = bit_cycles;
        next_sample = cyc + bitc + bitc / 2; // centre of data bit 0
      }
    } else if (cyc == next_sample) {
      if (nbit < 8) {
        data |= (uint8_t)(line & 1) << nbit;
        nbit++;
        next_sample += bitc;
      } else { // stop bit centre
        in_frame = false;
        frames++;
        if (line == 1) r = data; else framing_errors++;
      }
    }
    prev = line;
    return r;
  }
};

// ---------------- UART transmitter (drives uart0_rxd_i), as in the native harness ----------------
struct UartDriver {
  std::deque<uint8_t> q;
  bool active = false;
  int bit = 0;          // 0 = start, 1..8 = data, 9 = stop, 10 = idle gap
  uint16_t frame = 0;
  uint64_t next_edge = 0;
  unsigned bitc = 0;
  int line = 1;
  uint64_t sent = 0;
  inline void step(uint64_t cyc, bool uart_enabled, unsigned bit_cycles) {
    if (!active) {
      if (q.empty() || !uart_enabled) { line = 1; return; }
      frame = (uint16_t)((1u << 9) | ((unsigned)q.front() << 1)); // stop | data | start(0)
      q.pop_front();
      active = true; bit = 0; bitc = bit_cycles; next_edge = cyc + bitc;
      line = frame & 1;
      return;
    }
    if (cyc >= next_edge) {
      bit++;
      next_edge += bitc;
      if (bit <= 9) line = (frame >> bit) & 1;
      else if (bit == 10) line = 1; // one extra idle bit between frames
      else { active = false; sent++; line = 1; }
    }
  }
};

// ---------------- state ----------------
static Vneorv32_demo_wrapper* g_top = nullptr;
static uint64_t g_cycle = 0;
static unsigned g_reset_left = 0;
static bool g_probes_on = true;
static UartDecoder g_dec;
static UartDriver g_drv;
static uint32_t g_p[NEO_P_COUNT];
static uint32_t g_activity = 0;

static const uint32_t TXQ_SIZE = 1u << 16; // power of two
static uint8_t g_txq[TXQ_SIZE];
static uint32_t g_txq_head = 0, g_txq_tail = 0, g_txq_dropped = 0; // head = write, tail = read

static const uint32_t BUF_SIZE = 1u << 16;
static uint8_t g_buf[BUF_SIZE];

static const unsigned FALLBACK_BITC = 2u * (unsigned)(CLOCK_FREQUENCY / (2u * 19200u)); // bootloader default

static inline void txq_push(uint8_t b) {
  if (g_txq_head - g_txq_tail == TXQ_SIZE) { g_txq_tail++; g_txq_dropped++; } // drop oldest
  g_txq[g_txq_head++ & (TXQ_SIZE - 1)] = b;
}

static void clear_io() {
  g_dec = UartDecoder();
  g_drv = UartDriver();
  g_txq_head = g_txq_tail = g_txq_dropped = 0;
  memset(g_p, 0, sizeof g_p);
  g_activity = 0;
}

// ---------------- lifecycle ----------------
API int neo_init(void) {
  if (g_top) { g_top->final(); delete g_top; g_top = nullptr; }
  g_top = new Vneorv32_demo_wrapper;
  g_cycle = 0;
  g_reset_left = RESET_CYCLES;
  clear_io();
  g_top->clk_i = 0;
  g_top->rstn_i = 0;
  g_top->uart0_rxd_i = 1;
  g_top->eval();
  g_p[NEO_P_GPIO_OUT] = g_top->gpio_o;
  return 0;
}

API void neo_reset(void) {
  if (!g_top) { neo_init(); return; }
  g_reset_left = RESET_CYCLES;
  clear_io();
  g_p[NEO_P_GPIO_OUT] = g_top->gpio_o;
}

API uint32_t neo_step(uint32_t n) {
  if (!g_top) neo_init();
  Vneorv32_demo_wrapper* const top = g_top;
  auto* const r = top->rootp;
  uint32_t* const p = g_p;
  const uint32_t gpio_prev_window = p[NEO_P_GPIO_OUT];
  memset(p, 0, sizeof g_p);
  uint8_t last_gpio = (uint8_t)gpio_prev_window;
  uint32_t ran = 0;

  for (; ran < n; ran++) {
    if (Verilated::gotFinish()) break;
    // ---- inputs for this cycle ----
    top->rstn_i = g_reset_left == 0;
    const uint32_t ctrl = P_UART0_CTRL(r);
    const bool uart_en = ctrl & 1u;
    const unsigned bitc = uart_en ? uart_bit_cycles_from_ctrl(ctrl) : FALLBACK_BITC;
    const uint64_t sent_before = g_drv.sent;
    g_drv.step(g_cycle, uart_en, bitc);
    p[NEO_P_UART_RX_BYTES] += (uint32_t)(g_drv.sent - sent_before);
    top->uart0_rxd_i = g_drv.line;

    // ---- one clock cycle ----
    top->clk_i = 1; top->eval();
    top->clk_i = 0; top->eval();
    g_cycle++;
    if (g_reset_left) g_reset_left--;

    // ---- outputs ----
    if (g_probes_on) {
      const uint32_t is = P_CPU_IBUS_STB(r), ds = P_CPU_DBUS_STB(r);
      p[NEO_P_CPU_IFETCH] += is;
      if (is) p[NEO_P_LAST_IADDR] = P_CPU_IBUS_ADDR(r);
      p[NEO_P_CPU_DACC] += ds;
      if (ds) { p[NEO_P_LAST_DADDR] = P_CPU_DBUS_ADDR(r); p[NEO_P_CPU_DWR] += P_CPU_DBUS_RW(r); }
      p[NEO_P_CPU_SLEEP] += P_CPU_SLEEP(r);
      const uint32_t ims = P_IMEM_STB(r), dms = P_DMEM_STB(r);
      p[NEO_P_IMEM] += ims;
      p[NEO_P_IMEM_WR] += ims & P_IMEM_RW(r);
      p[NEO_P_DMEM] += dms;
      p[NEO_P_DMEM_WR] += dms & P_DMEM_RW(r);
      p[NEO_P_BOOTROM] += P_BOOTROM_STB(r);
      p[NEO_P_UART0] += P_UART0_STB(r);
      p[NEO_P_GPIO] += P_GPIO_STB(r);
      p[NEO_P_CLINT] += P_CLINT_STB(r);
      p[NEO_P_SYSINFO] += P_SYSINFO_STB(r);
      p[NEO_P_UART_TX_BUSY] += UART_ENGINE_BUSY(P_UART0_TX(r));
      p[NEO_P_UART_RX_BUSY] += UART_ENGINE_BUSY(P_UART0_RX(r));
      p[NEO_P_MTI] += P_CLINT_MTI(r);
    }
    const uint8_t g = top->gpio_o;
    if (g != last_gpio) { p[NEO_P_GPIO_TOGGLES]++; last_gpio = g; }

    const int ch = g_dec.step(top->uart0_txd_o, g_cycle, bitc);
    if (ch >= 0) { txq_push((uint8_t)ch); p[NEO_P_UART_TX_BYTES]++; }
  }

  p[NEO_P_CYCLES] = ran;
  p[NEO_P_GPIO_OUT] = top->gpio_o;
  p[NEO_P_UART_CTRL] = P_UART0_CTRL(r);
  const uint64_t mt = P_CLINT_MTIME(r);
  p[NEO_P_MTIME_LO] = (uint32_t)mt;
  p[NEO_P_MTIME_HI] = (uint32_t)(mt >> 32);
  if (!g_probes_on) p[NEO_P_LAST_IADDR] = p[NEO_P_LAST_DADDR] = 0;

  uint32_t a = 0;
  if (p[NEO_P_CPU_IFETCH] | p[NEO_P_CPU_DACC]) a |= NEO_A_CPU;
  if (p[NEO_P_IMEM]) a |= NEO_A_IMEM;
  if (p[NEO_P_DMEM]) a |= NEO_A_DMEM;
  if (p[NEO_P_BOOTROM]) a |= NEO_A_BOOTROM;
  if (p[NEO_P_UART0]) a |= NEO_A_UART0;
  if (p[NEO_P_GPIO]) a |= NEO_A_GPIO;
  if (p[NEO_P_CLINT]) a |= NEO_A_CLINT;
  if (p[NEO_P_SYSINFO]) a |= NEO_A_SYSINFO;
  if (p[NEO_P_UART_TX_BUSY] | p[NEO_P_UART_RX_BUSY]) a |= NEO_A_UART_LINE;
  if (p[NEO_P_GPIO_TOGGLES]) a |= NEO_A_GPIO_PIN;
  if (p[NEO_P_MTI]) a |= NEO_A_MTI;
  if (p[NEO_P_CPU_SLEEP]) a |= NEO_A_SLEEP;
  if (p[NEO_P_IMEM_WR] | p[NEO_P_DMEM_WR]) a |= NEO_A_MEM_WR;
  g_activity = a;
  return ran;
}

API double neo_cycles(void) { return (double)g_cycle; }
API int neo_finished(void) { return Verilated::gotFinish() ? 1 : 0; }
API uint32_t neo_clock_hz(void) { return CLOCK_FREQUENCY; }
API const char* neo_build_info(void) {
  return "NEORV32 v1.13.7 neorv32_test_setup_bootloader via GHDL synth -> Verilator " VERILATOR_VERSION
         ", CLOCK_FREQUENCY=" STR_(CLOCK_FREQUENCY)
#ifdef __EMSCRIPTEN__
         ", emscripten " STR_(__EMSCRIPTEN_MAJOR__) "." STR_(__EMSCRIPTEN_MINOR__) "." STR_(__EMSCRIPTEN_TINY__)
#else
         ", native"
#endif
      ;
}

// ---------------- UART ----------------
API int neo_uart_getc(void) {
  if (g_txq_tail == g_txq_head) return -1;
  return g_txq[g_txq_tail++ & (TXQ_SIZE - 1)];
}
API uint32_t neo_uart_tx_avail(void) { return g_txq_head - g_txq_tail; }
API uint32_t neo_uart_read(uint8_t* dst, uint32_t max) {
  uint32_t k = 0;
  while (k < max && g_txq_tail != g_txq_head) dst[k++] = g_txq[g_txq_tail++ & (TXQ_SIZE - 1)];
  return k;
}
API uint32_t neo_uart_tx_dropped(void) { return g_txq_dropped; }
API void neo_uart_putc(uint32_t byte) { g_drv.q.push_back((uint8_t)byte); }
API uint32_t neo_uart_write(const uint8_t* src, uint32_t n) {
  for (uint32_t i = 0; i < n; i++) g_drv.q.push_back(src[i]);
  return n;
}
API uint32_t neo_uart_rx_pending(void) { return (uint32_t)g_drv.q.size() + (g_drv.active ? 1u : 0u); }
API uint32_t neo_uart_bit_cycles(void) {
  if (!g_top) return FALLBACK_BITC;
  const uint32_t ctrl = P_UART0_CTRL(g_top->rootp);
  return (ctrl & 1u) ? uart_bit_cycles_from_ctrl(ctrl) : FALLBACK_BITC;
}
API uint8_t* neo_buf(void) { return g_buf; }
API uint32_t neo_buf_size(void) { return BUF_SIZE; }

// ---------------- pins / probes ----------------
API uint32_t neo_gpio(void) { return g_top ? g_top->gpio_o : 0; }
API uint32_t neo_uart_txd(void) { return g_top ? g_top->uart0_txd_o : 1; }
API const uint32_t* neo_probes(void) { return g_p; }
API uint32_t neo_probe(uint32_t idx) { return idx < NEO_P_COUNT ? g_p[idx] : 0; }
API uint32_t neo_probe_count(void) { return NEO_P_COUNT; }
API const char* neo_probe_names(void) { return NEO_PROBE_NAMES; }
API uint32_t neo_activity(void) { return g_activity; }
API const char* neo_activity_names(void) { return NEO_ACTIVITY_NAMES; }
API void neo_set_probes(int on) { g_probes_on = on != 0; }
