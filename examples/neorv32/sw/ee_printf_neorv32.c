// Minimal ee_printf for CoreMark on NEORV32 (fpa NEORV32 demo).
// Replaces newlib printf (HAS_PRINTF=0) so CoreMark fits a 16 KiB IMEM.
// Supports %[0][width][l|ll-ignored]{d,i,u,x,X,s,c,%}; all integers are 32-bit
// (CoreMark casts its %lu arguments to (long unsigned) = 32-bit on rv32).
#include <stdarg.h>
#include <stdint.h>
#include <neorv32.h>

static void out(char c) {
  if (c == '\n') {
    neorv32_uart0_putc('\r');
  }
  neorv32_uart0_putc(c);
}

static void out_num(uint32_t v, unsigned base, int neg, int width, char pad, int upper) {
  char buf[12];
  int n = 0;
  const char *digits = upper ? "0123456789ABCDEF" : "0123456789abcdef";
  do {
    buf[n++] = digits[v % base];
    v /= base;
  } while (v);
  int len = n + (neg ? 1 : 0);
  if (neg && pad == '0') {
    out('-');
  }
  while (width-- > len) {
    out(pad);
  }
  if (neg && pad != '0') {
    out('-');
  }
  while (n) {
    out(buf[--n]);
  }
}

int ee_printf(const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  char c;
  while ((c = *fmt++)) {
    if (c != '%') {
      out(c);
      continue;
    }
    char pad = ' ';
    int width = 0;
    if (*fmt == '0') {
      pad = '0';
      fmt++;
    }
    while (*fmt >= '0' && *fmt <= '9') {
      width = width * 10 + (*fmt++ - '0');
    }
    while (*fmt == 'l') {
      fmt++;
    }
    c = *fmt++;
    switch (c) {
      case 'd': case 'i': {
        int32_t s = va_arg(ap, int32_t);
        out_num(s < 0 ? (uint32_t)(-s) : (uint32_t)s, 10, s < 0, width, pad, 0);
        break;
      }
      case 'u': out_num(va_arg(ap, uint32_t), 10, 0, width, pad, 0); break;
      case 'x': out_num(va_arg(ap, uint32_t), 16, 0, width, pad, 0); break;
      case 'X': out_num(va_arg(ap, uint32_t), 16, 0, width, pad, 1); break;
      case 's': { const char *s = va_arg(ap, const char *); while (*s) out(*s++); break; }
      case 'c': out((char)va_arg(ap, int)); break;
      case '%': out('%'); break;
      case 0: fmt--; break;
      default: out('%'); out(c); break;
    }
  }
  va_end(ap);
  return 0;
}
