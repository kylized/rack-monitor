#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIDS=()

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { echo -e "${CYAN}[start]${NC} $*"; }
ok()   { echo -e "${GREEN}[  ok ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*"; }

cleanup() {
    echo ""
    log "Shutting down all services..."
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null && ok "Killed PID $pid"
        fi
    done
    wait 2>/dev/null
    log "Done."
}
trap cleanup EXIT INT TERM

# ── Kill any leftover processes from previous runs ────────────────────────────
for port in 5001 8554; do
    lsof -ti ":$port" 2>/dev/null | xargs kill -9 2>/dev/null || true
done
pkill -9 -f "native_app/main.py" 2>/dev/null || true
sleep 1

# ── Find Python per service ───────────────────────────────────────────────────
RA_PYTHON="$ROOT/ra/.venv/bin/python"
APP_PYTHON="$ROOT/native_app/.venv/bin/python"

if [[ ! -x "$RA_PYTHON" ]]; then
    err "RA venv not found at $RA_PYTHON — run: cd ra && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi
if [[ ! -x "$APP_PYTHON" ]]; then
    err "native_app venv not found at $APP_PYTHON"
    exit 1
fi
ok "RA Python:  $RA_PYTHON"
ok "App Python: $APP_PYTHON"

# ── 1. mediamtx ──────────────────────────────────────────────────────────────
MTXBIN="$ROOT/mediamtx/mediamtx"
MTXCFG="$ROOT/mediamtx/mediamtx.yml"
if [[ ! -x "$MTXBIN" ]]; then
    warn "mediamtx binary not found at $MTXBIN — skipping RTSP server"
else
    log "Starting mediamtx..."
    "$MTXBIN" "$MTXCFG" > "$ROOT/mediamtx.log" 2>&1 &
    _pid=$!; PIDS+=($_pid)
    ok "mediamtx started (PID $_pid, log: mediamtx.log)"
fi

# ── 2. Rack Analyzer backend ──────────────────────────────────────────────────
log "Starting RA backend (port 5001)..."
(cd "$ROOT/ra" && exec "$RA_PYTHON" main.py) > "$ROOT/ra.log" 2>&1 &
_pid=$!; PIDS+=($_pid)
ok "RA backend started (PID $_pid, log: ra.log)"

# ── 3. Native camera app ──────────────────────────────────────────────────────
log "Starting native camera overlay app..."
(cd "$ROOT/native_app" && exec "$APP_PYTHON" main.py) > "$ROOT/native_app.log" 2>&1 &
_pid=$!; PIDS+=($_pid)
ok "Native app started (PID $_pid, log: native_app.log)"

# ── 4. Web frontend ───────────────────────────────────────────────────────────
# Brief pause so RA backend is ready before the browser opens
sleep 1
log "Opening web frontend..."
open "$ROOT/index.html" 2>/dev/null || xdg-open "$ROOT/index.html" 2>/dev/null || \
    warn "Could not auto-open browser — visit file://$ROOT/index.html"

echo ""
echo -e "${GREEN}All services running. Press Ctrl+C to stop everything.${NC}"
echo ""
echo -e "  RA backend   → ${CYAN}http://localhost:5001${NC}"
echo -e "  RTSP server  → ${CYAN}rtsp://localhost:8554${NC}"
echo -e "  Logs         → mediamtx.log / ra.log / native_app.log"
echo ""

# Keep script alive; child processes log to files
wait
