#!/usr/bin/env bash
# BetsWin - start the engine and the dashboard together.
#
#   ./start.sh            live markets
#   ./start.sh --demo     offline fixtures, no network
#
# Ports can be overridden:  API_PORT=8001 WEB_PORT=3001 ./start.sh
#
# Nothing here kills another process. If a port is taken the script moves to a
# free one and tells you, so a stray server from an earlier run cannot leave you
# staring at a window that closed before you could read it.

set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
engine_pid=""
started_engine=false

# ------------------------------------------------------------------ output

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; RESET=""
fi

info()  { printf '%s\n' "${CYAN}$*${RESET}"; }
note()  { printf '%s\n' "${DIM}$*${RESET}"; }
warn()  { printf '%s\n' "${YELLOW}$*${RESET}"; }
ok()    { printf '%s\n' "${GREEN}$*${RESET}"; }

# Double-clicking a .sh in Explorer opens a window that vanishes the instant the
# script ends. Hold it open on failure so the message is actually readable.
die() {
  printf '\n%s\n' "${RED}${BOLD}Cannot start BetsWin${RESET}"
  printf '%s\n' "${RED}$*${RESET}"
  if [[ -t 0 ]]; then
    printf '\n%s' "${DIM}Press Enter to close...${RESET}"
    read -r _ || true
  fi
  exit 1
}

cleanup() {
  if [[ -n "$engine_pid" ]] && $started_engine; then
    kill "$engine_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ------------------------------------------------------------------- ports

port_busy() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&- 2>/dev/null; return 0; }
  return 1
}

first_free_port() {
  local p="$1"
  for _ in $(seq 1 40); do
    port_busy "$p" || { printf '%s' "$p"; return 0; }
    p=$((p + 1))
  done
  printf '%s' "$1"
}

# Is an existing BetsWin engine already answering on this port?
engine_alive_on() {
  curl -fsS -m 2 "http://127.0.0.1:$1/api/health" 2>/dev/null | grep -q '"ok":true'
}

# ----------------------------------------------------------------- options

DEMO=false
for arg in "$@"; do
  case "$arg" in
    --demo) DEMO=true ;;
    -h|--help)
      printf '%s\n' "Usage: ./start.sh [--demo]"
      printf '%s\n' "  --demo   run on offline fixtures, no network required"
      printf '%s\n' "Environment: API_PORT (default 8000), WEB_PORT (default 3000)"
      exit 0
      ;;
    *) die "Unknown option: $arg
Run ./start.sh --help to see the available options." ;;
  esac
done
export DEMO_MODE=$DEMO

# ----------------------------------------------------------- prerequisites

command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 \
  || die "Python is not on your PATH.
Install Python 3.11 or later, then reopen this terminal."
PYTHON=$(command -v python 2>/dev/null || command -v python3)

command -v node >/dev/null 2>&1 \
  || die "Node.js is not on your PATH.
Install Node 18 or later, then reopen this terminal."

[[ -d "$root/frontend/node_modules" ]] \
  || die "The dashboard's dependencies are not installed.
Run this first:

    cd \"$root/frontend\" && npm install"

"$PYTHON" -c "import fastapi, httpx, pydantic_settings" 2>/dev/null \
  || die "The engine's Python dependencies are not installed.
Run this first:

    cd \"$root/backend\" && pip install -r requirements.txt"

# ------------------------------------------------------------ engine start

printf '\n%s\n' "${BOLD}BetsWin${RESET}${DIM}  ·  $($DEMO && echo 'demo fixtures' || echo 'live markets')${RESET}"

if port_busy "$API_PORT"; then
  if engine_alive_on "$API_PORT"; then
    ok "An engine is already running on port $API_PORT - reusing it."
    note "  Stop it first if you wanted a fresh one with different settings."
  else
    new_api=$(first_free_port $((API_PORT + 1)))
    warn "Port $API_PORT is taken by something else; using $new_api instead."
    API_PORT="$new_api"
  fi
fi

if ! engine_alive_on "$API_PORT"; then
  info "Starting the arbitrage engine on http://127.0.0.1:$API_PORT ..."
  (
    cd "$root/backend" || exit 1
    exec "$PYTHON" -m arbengine.main --port "$API_PORT"
  ) &
  engine_pid=$!
  started_engine=true

  ready=false
  for _ in $(seq 1 60); do
    if engine_alive_on "$API_PORT"; then ready=true; break; fi
    # If the engine died, stop waiting and say so.
    if ! kill -0 "$engine_pid" 2>/dev/null; then
      die "The engine exited while starting up.
Run it directly to see the error:

    cd \"$root/backend\" && $PYTHON -m arbengine.main --port $API_PORT"
    fi
    sleep 1
  done
  $ready || die "The engine did not respond within 60 seconds.
Check $root/backend/logs/scanner.log for the reason."
  ok "Engine ready."
fi

# --------------------------------------------------------- dashboard start

if port_busy "$WEB_PORT"; then
  new_web=$(first_free_port $((WEB_PORT + 1)))
  warn "Port $WEB_PORT is already in use; the dashboard will use $new_web instead."
  note "  (Something is already listening there - probably a dashboard you left running.)"
  WEB_PORT="$new_web"
fi

# Tell the frontend where the engine actually ended up, in case either port moved.
export NEXT_PUBLIC_API_URL="http://127.0.0.1:$API_PORT"
export NEXT_PUBLIC_WS_URL="ws://127.0.0.1:$API_PORT/ws"

printf '\n'
ok "Dashboard  ->  http://localhost:$WEB_PORT"
note "API        ->  http://127.0.0.1:$API_PORT  (docs at /docs)"
note "Press Ctrl-C to stop."
printf '\n'

cd "$root/frontend" || die "Cannot enter $root/frontend"

started_at=$SECONDS
npx next dev -p "$WEB_PORT"
status=$?
ran_for=$((SECONDS - started_at))

# A dev server that ran for a while and then stopped was shut down on purpose --
# Ctrl-C, a closed window, an outside signal -- and none of that is an error.
# Only a fast exit means it never managed to start.
if [[ $status -ne 0 && $ran_for -lt 10 ]]; then
  die "The dashboard failed to start (exit status $status).
If it reported a port conflict, close the other server or pick another port:

    WEB_PORT=$((WEB_PORT + 1)) ./start.sh$($DEMO && echo ' --demo')"
fi

printf '\n%s\n' "${DIM}Dashboard stopped.${RESET}"
