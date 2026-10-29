#!/usr/bin/env bash
# =============================================================================
# Rebuild the NEORV32 demo site (docs/demo/neorv32/) from pinned upstream sources.
#
#   NEORV32 v1.13.7 rtl (unmodified) + rtl/neorv32_demo_wrapper.vhd
#     -> GHDL synth -> Verilog -> Verilator (+ sim/probes.vlt) -> C++
#     -> em++ with sim/neorv32_sim_api.cpp -> neorv32_sim.{js,wasm}
#   NEORV32 sw (xPack GCC)       -> programs/*.bin (bootloader-uploadable)
#   fpa build + view             -> design.html (the diagram, shipped as is)
#   GHDL elaboration + tools/fpa_map.py -> fpa-map.json (checked probe->node table)
#   web/*                        -> index.html, app.js, sim-worker.js, style.css
#
# usage:  bash examples/neorv32/build.sh
# env (defaults in brackets):
#   CACHE      [~/.cache/neorv32-demo]   TOOLS [$CACHE/tools]   WORK [$CACHE/demo-build]
#   SRC        [$CACHE/src]  pinned clones (cloned if missing): neorv32, neorv32-setups, neorv32-coremark
#   GHDL       [$TOOLS/ghdl-mcode-6.0.0-ubuntu24.04-x86_64/bin/ghdl]
#   XPACK_BIN  [$TOOLS/xpack-riscv-none-elf-gcc-15.2.0-1/bin]
#   EMSDK_DIR  [$TOOLS/emsdk]  EMSDK_VER [6.0.13]  VERILATOR [verilator, tested with 5.052]
#   OUT        [<repo>/docs/demo/neorv32]
# GHDL, xPack GCC and emsdk are fetched into $TOOLS if missing (sha256-checked tarballs).
# Nothing outside $WORK, $TOOLS, $SRC and $OUT is written; the fpa code is only run.
# =============================================================================
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
CACHE=${CACHE:-$HOME/.cache/neorv32-demo}
TOOLS=${TOOLS:-$CACHE/tools}
WORK=${WORK:-$CACHE/demo-build}
SRC=${SRC:-$CACHE/src}
OUT=${OUT:-$REPO/docs/demo/neorv32}
CLK=1000000   # CLOCK_FREQUENCY generic; the page paces 1 M cycles/s = real time

GHDL_NAME=ghdl-mcode-6.0.0-ubuntu24.04-x86_64
GHDL_URL=https://github.com/ghdl/ghdl/releases/download/v6.0.0/$GHDL_NAME.tar.gz
GHDL_SHA256=30d6a977b8456d140bbafecbbe64b1947a3d92eeae8f5e6d9f528a174f9566e7
XPACK_NAME=xpack-riscv-none-elf-gcc-15.2.0-1
XPACK_URL=https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v15.2.0-1/$XPACK_NAME-linux-x64.tar.gz
XPACK_SHA256=aaaa8060c914851a3e5ee1ba82cc3d6f80972f90638a05c6e823a37557a33758
GHDL=${GHDL:-$TOOLS/$GHDL_NAME/bin/ghdl}
XPACK_BIN=${XPACK_BIN:-$TOOLS/$XPACK_NAME/bin}
EMSDK_DIR=${EMSDK_DIR:-$TOOLS/emsdk}
EMSDK_VER=${EMSDK_VER:-6.0.13}
VERILATOR=${VERILATOR:-verilator}
PY=${PY:-python3}

NEORV32_URL=https://github.com/stnolting/neorv32.git
NEORV32_TAG=v1.13.7
NEORV32_REV=b1f307244928161a3fca1a010af11d5a736b5339
SETUPS_URL=https://github.com/stnolting/neorv32-setups.git
SETUPS_REV=57f86d5ad3fa54f6919165b7bcc61fad9a5cae0a       # only for the Arty A7 XDC
COREMARK_URL=https://github.com/stnolting/neorv32-coremark.git
COREMARK_REV=e1553f10106faf3edfb34d86780b414782bc2aea     # its 'coremark' submodule = eembc/coremark 1f483d5
TOP=neorv32_test_setup_bootloader
FPA="$REPO/skills/fpga-project-analyzer/scripts/fpa.py"

log() { printf '\n=== %s\n' "$*"; }
T0=$(date +%s)

# ---------------------------------------------------------------- 1. tools + sources
log "1. tools and pinned sources"
fetch_tool() { # dir-name url sha256 binary
  [ -x "$TOOLS/$1/bin/$4" ] && return 0
  mkdir -p "$TOOLS/dl"
  [ -f "$TOOLS/dl/$1.tar.gz" ] || curl -fL --retry 3 -o "$TOOLS/dl/$1.tar.gz" "$2"
  echo "$3  $TOOLS/dl/$1.tar.gz" | sha256sum -c -
  tar -xzf "$TOOLS/dl/$1.tar.gz" -C "$TOOLS"
}
[ -x "$GHDL" ] || fetch_tool "$GHDL_NAME" "$GHDL_URL" "$GHDL_SHA256" ghdl
[ -x "$XPACK_BIN/riscv-none-elf-gcc" ] || fetch_tool "$XPACK_NAME" "$XPACK_URL" "$XPACK_SHA256" riscv-none-elf-gcc
if [ ! -x "$EMSDK_DIR/emsdk" ]; then git clone -q https://github.com/emscripten-core/emsdk.git "$EMSDK_DIR"; fi
if ! ( cd "$EMSDK_DIR" && ./emsdk list 2>/dev/null | grep -qE "^\s+\*?\s*$EMSDK_VER\s.*INSTALLED" ); then
  ( cd "$EMSDK_DIR" && ./emsdk install "$EMSDK_VER" )
fi
( cd "$EMSDK_DIR" && ./emsdk activate "$EMSDK_VER" >/dev/null )
# shellcheck disable=SC1091
EMSDK_QUIET=1 source "$EMSDK_DIR/emsdk_env.sh"

fetch_git() { # dir url rev
  local d=$1
  if [ ! -d "$d/.git" ]; then git init -q "$d"; git -C "$d" remote add origin "$2"; fi
  if [ "$(git -C "$d" rev-parse -q --verify HEAD 2>/dev/null || true)" != "$3" ]; then
    git -C "$d" fetch -q --depth 1 origin "$3"
    git -C "$d" checkout -q --detach FETCH_HEAD
  fi
  [ "$(git -C "$d" rev-parse HEAD)" = "$3" ] || { echo "$d is not at $3"; exit 1; }
}
mkdir -p "$SRC"
NEO=$SRC/neorv32
fetch_git "$NEO" "$NEORV32_URL" "$NEORV32_REV"
fetch_git "$SRC/neorv32-setups" "$SETUPS_URL" "$SETUPS_REV"
fetch_git "$SRC/neorv32-coremark" "$COREMARK_URL" "$COREMARK_REV"
[ -f "$SRC/neorv32-coremark/coremark/core_main.c" ] || git -C "$SRC/neorv32-coremark" submodule update -q --init --depth 1 coremark
XDC=$SRC/neorv32-setups/vivado/arty-a7-test-setup/arty_a7_test_setup.xdc
echo "NEORV32 $NEORV32_TAG ($NEORV32_REV)"
"$GHDL" version | head -1
"$VERILATOR" --version
em++ --version | head -1
"$XPACK_BIN/riscv-none-elf-gcc" --version | head -1
rm -rf "$WORK"; mkdir -p "$WORK"/{ghdl,sim,site/programs}

# ---------------------------------------------------------------- 2. VHDL -> Verilog (+ elaborated tree)
log "2. GHDL: VHDL -> Verilog (CLOCK_FREQUENCY=$CLK)"
mapfile -t VHDL < <(sed "s|\$NEORV32_HOME|$NEO|" "$NEO/rtl/file_list_core.f" | grep -v '^$')
VHDL+=("$NEO/rtl/test_setups/$TOP.vhd" "$HERE/rtl/neorv32_demo_wrapper.vhd")
GW=(--std=08 --work=neorv32 --workdir="$WORK/ghdl")
"$GHDL" -i "${GW[@]}" "${VHDL[@]}"
"$GHDL" -m "${GW[@]}" neorv32_demo_wrapper
"$GHDL" synth "${GW[@]}" -gCLOCK_FREQUENCY="$CLK" --out=verilog neorv32_demo_wrapper \
  > "$WORK/sim/neorv32_demo_wrapper.v" 2> "$WORK/ghdl_synth.log"
echo "Verilog: $(wc -l < "$WORK/sim/neorv32_demo_wrapper.v") lines"
# ground truth for the diagram: which instances exist with these generics
"$GHDL" --elab-run "${GW[@]}" "$TOP" --disp-tree=inst --stop-time=0ns > "$WORK/ghdl.tree.txt" 2>&1 || true
grep -q "neorv32_top_inst \[instance\]" "$WORK/ghdl.tree.txt"

# ---------------------------------------------------------------- 3. Verilator -> em++ -> wasm
log "3. Verilator + em++ -> neorv32_sim.{js,wasm}"
MDIR=$WORK/sim/obj_dir
"$VERILATOR" --cc --top-module neorv32_demo_wrapper --Mdir "$MDIR" \
  -O3 --x-assign fast --x-initial unique --noassert -Wno-fatal -Wno-lint -Wno-style \
  "$HERE/sim/probes.vlt" "$WORK/sim/neorv32_demo_wrapper.v" > "$WORK/verilator.log" 2>&1 \
  || { tail -40 "$WORK/verilator.log"; exit 1; }
VINC=$("$VERILATOR" --getenv VERILATOR_ROOT)/include
# -include stdint.h: svdpi.h only includes <inttypes.h> under __linux (not defined by Emscripten).
# vl_wasm_stubs.cpp: pthread affinity / sched_getcpu stubs the single-threaded runtime never calls.
CFLAGS=(-O3 -flto -include stdint.h -std=gnu++17 -I"$VINC" -I"$VINC/vltstd" -I"$MDIR" -I"$HERE/sim"
        -DVERILATOR=1 -DVM_COVERAGE=0 -DVM_SC=0 -DVM_TIMING=0 -DVM_TRACE=0 -DVM_TRACE_FST=0
        -DVM_TRACE_VCD=0 -DVM_TRACE_SAIF=0 -DVM_VPI=0 -DCLOCK_FREQUENCY="$CLK" -faligned-new
        -Wno-bool-operation -Wno-shadow -Wno-sign-compare -Wno-tautological-compare
        -Wno-uninitialized -Wno-unused-parameter -Wno-unused-variable)
mkdir -p "$WORK/sim/o"; pids=()
for s in "$MDIR"/Vneorv32_demo_wrapper*.cpp "$VINC"/verilated.cpp "$VINC"/verilated_dpi.cpp \
         "$VINC"/verilated_threads.cpp "$HERE"/sim/neorv32_sim_api.cpp "$HERE"/sim/vl_wasm_stubs.cpp; do
  em++ "${CFLAGS[@]}" -c "$s" -o "$WORK/sim/o/$(basename "$s" .cpp).o" & pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
em++ -O3 -flto "$WORK"/sim/o/*.o -o "$WORK/site/neorv32_sim.js" \
  -sMODULARIZE=1 -sEXPORT_ES6=1 -sEXPORT_NAME=createNeorv32 -sALLOW_MEMORY_GROWTH=1 \
  -sENVIRONMENT=web,worker,node -sEXPORTED_RUNTIME_METHODS=HEAPU8,HEAPU32,UTF8ToString -sFILESYSTEM=0
ls -l "$WORK/site/neorv32_sim.js" "$WORK/site/neorv32_sim.wasm"

# ---------------------------------------------------------------- 4. RISC-V programs
log "4. programs (xPack GCC, rv32imc, IMEM 16 KiB @0, DMEM 8 KiB @0x80000000)"
export PATH=$XPACK_BIN:$PATH
cp -r "$NEO/sw" "$WORK/sw"
NH=$WORK   # NEORV32_HOME: holds only sw/
MK=(NEORV32_HOME="$NH" MARCH=rv32imc_zicsr_zifencei MABI=ilp32
    LDFLAGS="-Wl,--defsym,__neorv32_rom_base=0x00000000 -Wl,--defsym,__neorv32_rom_size=16k -Wl,--defsym,__neorv32_ram_base=0x80000000 -Wl,--defsym,__neorv32_ram_size=8k")
build_prog() { # name dir
  make -s -C "$2" NEORV32_HOME="$NH" clean > /dev/null
  make -s -C "$2" "${MK[@]}" exe > "$WORK/sw_$1.log" 2>&1 || { tail -20 "$WORK/sw_$1.log"; exit 1; }
  cp "$2/neorv32_exe.bin" "$WORK/site/programs/$1.bin"
  printf '  %-20s %6d bytes\n' "$1" "$(stat -c %s "$2/neorv32_exe.bin")"
}
for p in hello_world demo_blink_led demo_clint bus_explorer; do build_prog "$p" "$WORK/sw/example/$p"; done
# Game of Life with a 64x20 universe (upstream: 160x40, needs a 162x43 terminal)
GOL=$WORK/sw/example/game_of_life_64x20; mkdir -p "$GOL"
sed -e 's/^#define NUM_CELLS_X (160)/#define NUM_CELLS_X (64)/' -e 's/^#define NUM_CELLS_Y (40)/#define NUM_CELLS_Y (20)/' \
  "$WORK/sw/example/game_of_life/main.c" > "$GOL/main.c"
grep -q 'NUM_CELLS_X (64)' "$GOL/main.c" && grep -q 'NUM_CELLS_Y (20)' "$GOL/main.c"
cp "$WORK/sw/example/game_of_life/Makefile" "$GOL/"
build_prog game_of_life_64x20 "$GOL"
# "benchmark": derived from EEMBC CoreMark sources (Apache-2.0), 1 iteration, sized for 16K/8K:
# tiny ee_printf (HAS_PRINTF=0), no float, static memory. EEMBC's terms reserve the CoreMark name
# for unmodified, rule-conforming runs, so this modified copy is renamed in its output, and its
# 10-second minimum-runtime check (which only flags short runs; CRCs still validate) is removed.
CM=$WORK/benchmark; mkdir -p "$CM"
cp -r "$SRC/neorv32-coremark/coremark" "$CM/coremark"; rm -rf "$CM/coremark/.git"
cp "$HERE/sw/ee_printf_neorv32.c" "$CM/"
sed -e 's/^#define ITERATIONS (2000)/#define ITERATIONS (1)/' "$SRC/neorv32-coremark/core_portme.h" > "$CM/core_portme.h"
grep -q 'ITERATIONS (1)' "$CM/core_portme.h"
sed -e 's|^  neorv32_uart0_printf("\\nExecution completed.\\n");|  { uint32_t t = (uint32_t)(stop_time_val - start_time_val); uint32_t k = t ? (uint32_t)(((uint64_t)ITERATIONS * 1000000000ULL) / t) : 0; ee_printf("\\nResult: %u iteration(s) in %u cycles = %u.%03u iterations/MHz\\n", (uint32_t)ITERATIONS, t, k / 1000, k % 1000); }\n  neorv32_uart0_printf("\\nExecution completed.\\n");|' \
    -e 's|"\\nCoreMark on NEORV32 (v"|"\\nBenchmark on NEORV32 (v"|' \
    -e 's|"Running coremark (|"Running benchmark (|' \
  "$SRC/neorv32-coremark/core_portme.c" > "$CM/core_portme.c"
grep -q 'iterations/MHz' "$CM/core_portme.c" && grep -q 'Benchmark on NEORV32' "$CM/core_portme.c" && grep -q 'Running benchmark' "$CM/core_portme.c"
perl -0pi -e 's/if \(time_in_secs\(total_time\) < 10\)\s*\{.*?total_errors\+\+;\s*\}\n//s;
              s/"CoreMark Size    : /"Data size        : /;
              s/ for coremark\.\\n/.\\n/g;
              s/"Correct operation validated\. See README\.md for run and reporting "\s*"rules\.\\n"/"Correct operation validated (CRCs match).\\n"/s' "$CM/coremark/core_main.c"
! grep -q 'Must execute for at least 10 secs\|CoreMark Size\|for coremark\|reporting "' "$CM/coremark/core_main.c"
cat > "$CM/Makefile" <<EOF
EFFORT = -Os
USER_FLAGS += -DMULTITHREAD=1 -DHAS_PRINTF=0 -DHAS_FLOAT=0 -DMEM_METHOD=MEM_STATIC
APP_SRC += \$(wildcard coremark/*.c) core_portme.c ee_printf_neorv32.c
APP_INC += -I coremark -I .
include \$(NEORV32_HOME)/sw/common/common.mk
EOF
build_prog benchmark "$CM"

# ---------------------------------------------------------------- 5. fpa diagram + checked map
log "5. fpa: diagram of the unmodified test setup + Arty A7 XDC"
P=$WORK/fpa_proj; mkdir -p "$P/rtl/core" "$P/rtl/test_setups" "$P/constraints"
: > "$P/rtl/file_list.f"
while read -r f; do
  [ -z "$f" ] && continue
  cp "${f/\$NEORV32_HOME/$NEO}" "$P/rtl/core/"; echo "core/$(basename "$f")" >> "$P/rtl/file_list.f"
done < "$NEO/rtl/file_list_core.f"
cp "$NEO/rtl/test_setups/$TOP.vhd" "$P/rtl/test_setups/"; echo "test_setups/$TOP.vhd" >> "$P/rtl/file_list.f"
cp "$XDC" "$P/constraints/"
export PYTHONDONTWRITEBYTECODE=1
"$PY" "$FPA" build "$P" --top "$TOP" --vivado off > "$WORK/fpa_build.txt"; head -4 "$WORK/fpa_build.txt"
"$PY" "$FPA" view "$P" -o "$WORK/site/design.html"
# the only build-machine detail in the page: meta.root (the local project path, not displayed)
"$PY" -I - "$WORK/site/design.html" "$P" <<'PY'
import sys
f, root = sys.argv[1], sys.argv[2]
s = open(f, encoding="utf-8").read()
old = '"root":"%s"' % root
assert s.count(old) == 1, "meta.root not found once"
open(f, "w", encoding="utf-8").write(s.replace(old, '"root":"neorv32_test_setup_bootloader"'))
PY
"$PY" -I "$HERE/tools/fpa_map.py" "$WORK/site/design.html" "$WORK/ghdl.tree.txt" \
  "$HERE/web/activity-map.json" "$HERE/sim/neorv32_sim_api.cpp" "$WORK/site/fpa-map.json"

# ELK layouts of every real level, computed once here (the neorv32_top level takes about a minute of
# ELK time; the page answers it from layouts.json, see web/fpa-shim.js). RECORD_LAYOUTS=0 skips this;
# the page then lays out big levels in a Web Worker.
if [ "${RECORD_LAYOUTS:-1}" = 1 ]; then
  log "5b. ELK layouts (headless Chrome: ${CHROME:=$(command -v google-chrome-stable || command -v google-chrome || command -v chromium)})"
  "$PY" -I "$HERE/tools/inject_shim.py" record "$WORK/site/design.html" "$HERE/web/fpa-shim.js" "$WORK/record.html"
  PROFILE="$WORK/chrome-profile"; mkdir -p "$PROFILE"   # inside $WORK: wiped on the next build
  "$CHROME" --headless=new --no-first-run --no-default-browser-check --user-data-dir="$PROFILE" \
    --remote-debugging-port="${DEVTOOLS_PORT:-19333}" about:blank > "$WORK/chrome.log" 2>&1 &
  CHR=$!
  for _ in $(seq 50); do curl -sf "http://127.0.0.1:${DEVTOOLS_PORT:-19333}/json/version" > /dev/null && break; sleep 0.2; done
  ${NODE:-node} "$HERE/tools/record_layouts.mjs" "${DEVTOOLS_PORT:-19333}" "file://$WORK/record.html" \
    "$WORK/site/fpa-map.json" "$WORK/site/layouts.json" || { kill $CHR; exit 1; }
  kill $CHR; wait $CHR 2>/dev/null || true
  rm -rf "$PROFILE" 2>/dev/null || true   # Chrome helpers may still be writing; best effort
else
  echo '{}' > "$WORK/site/layouts.json"
fi

# ---------------------------------------------------------------- 6. site
log "6. site -> $OUT"
cp "$HERE"/web/{index.html,app.js,sim-worker.js,fpa-shim.js,style.css,programs.json} "$WORK/site/"
"$PY" -I - "$WORK/site" <<'PY'
import json, os, struct, sys
site = sys.argv[1]
progs = json.load(open(os.path.join(site, "programs.json")))
for p in progs:
    b = open(os.path.join(site, p["file"]), "rb").read()
    sig, base, size, _ = struct.unpack("<4I", b[:16])
    assert sig == 0x214F454E and base == 0 and size == len(b) - 16 <= 16384, p
    p["bytes"] = len(b)
json.dump(progs, open(os.path.join(site, "programs.json"), "w"), indent=1)
print("programs.json: %d programs, all signed, base 0, <= 16 KiB" % len(progs))
PY
{ cat <<EOF
Third-party components in this directory (the NEORV32 demo of the FPGA Project Analyzer)
=======================================================================================

* neorv32_sim.wasm / neorv32_sim.js: NEORV32 ${NEORV32_TAG} RTL (BSD-3-Clause, license below),
  converted by GHDL and Verilator; it includes the Verilator runtime (LGPL-3.0-only or
  Artistic-2.0, https://verilator.org) and the Emscripten runtime and libc (MIT / NCSA,
  https://github.com/emscripten-core/emscripten). The boot ROM image inside it is the NEORV32
  bootloader shipped with the RTL.
* programs/*.bin: NEORV32 ${NEORV32_TAG} example programs and software library (BSD-3-Clause,
  license below). game_of_life_64x20 is upstream game_of_life with a smaller universe.
* programs/benchmark.bin: derived from EEMBC CoreMark (https://github.com/eembc/coremark) with the
  NEORV32 port (https://github.com/stnolting/neorv32-coremark), Apache-2.0
  (http://www.apache.org/licenses/LICENSE-2.0). Modified: 1 iteration, minimal printf, no float,
  static memory, no 10-second runtime rule, renamed output; sized for 16 KiB IMEM. Its results
  are not CoreMark scores. CoreMark is a trademark of EEMBC.
* design.html: generated by the FPGA Project Analyzer (MIT); it embeds elkjs (EPL-2.0,
  https://github.com/kieler/elkjs).

----------------------------------------------------------------------------------------
NEORV32 license (https://github.com/stnolting/neorv32/blob/${NEORV32_TAG}/LICENSE)
----------------------------------------------------------------------------------------
EOF
cat "$NEO/LICENSE"; } > "$WORK/site/THIRD_PARTY.txt"
rm -rf "$OUT"; mkdir -p "$OUT"; cp -r "$WORK/site/." "$OUT/"
touch "$REPO/docs/.nojekyll"
( cd "$OUT" && find . -type f -printf '%8s  %p\n' | sort -k2 )
echo "total: $(du -sb "$OUT" | cut -f1) bytes"
log "done in $(( $(date +%s) - T0 )) s -> $OUT"
