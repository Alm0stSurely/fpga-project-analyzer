#!/usr/bin/env bash
# Serve docs/ locally and run test/check.mjs against the demo in headless Chrome.
# usage: bash examples/neorv32/test/run.sh [out dir]   (env: CHROME, PORT, DEVTOOLS_PORT, USER_BIN)
# USER_BIN is the file "uploaded" through the page's file input (default: a bus_explorer
# build from the build dir, i.e. a file from outside the site).
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
OUT=${1:-${TMPDIR:-/tmp}/neorv32-demo-check}
PORT=${PORT:-18790}
DT=${DEVTOOLS_PORT:-19222}
CHROME=${CHROME:-$(command -v google-chrome-stable || command -v google-chrome || command -v chromium)}
USER_BIN=${USER_BIN:-${WORK:-$HOME/.cache/neorv32-demo/demo-build}/sw/example/bus_explorer/neorv32_exe.bin}
mkdir -p "$OUT"
PROFILE=$(mktemp -d)
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$REPO/docs" > "$OUT/http.log" 2>&1 &
SRV=$!
"$CHROME" --headless=new --no-first-run --no-default-browser-check --user-data-dir="$PROFILE" \
  --remote-debugging-port="$DT" --window-size=1600,1000 about:blank > "$OUT/chrome.log" 2>&1 &
CHR=$!
trap 'kill $SRV $CHR 2>/dev/null; wait $CHR 2>/dev/null; rm -rf "$PROFILE"' EXIT
for _ in $(seq 50); do curl -sf "http://127.0.0.1:$DT/json/version" > /dev/null && break; sleep 0.2; done
"$CHROME" --version
node "$HERE/check.mjs" "http://127.0.0.1:$PORT/demo/neorv32/" "$DT" "$USER_BIN" "$OUT"
