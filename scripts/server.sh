#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
VENV_PY="$ROOT_DIR/.venv/bin/python"
UVICORN_LOG="$RUN_DIR/uvicorn.log"
UVICORN_PID_FILE="$RUN_DIR/uvicorn.pid"

load_env() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT_DIR/.env"
    set +a
  fi
}

ensure_dirs() {
  mkdir -p "$RUN_DIR"
}

is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

start_app() {
  ensure_dirs
  if [[ ! -x "$VENV_PY" ]]; then
    echo "Missing venv at $VENV_PY"
    exit 1
  fi

  load_env
  export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

  if [[ -f "$UVICORN_PID_FILE" ]]; then
    local pid
    pid="$(cat "$UVICORN_PID_FILE")"
    if is_pid_running "$pid"; then
      echo "App already running (pid $pid)"
      return 0
    fi
  fi

  "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > "$UVICORN_LOG" 2>&1 &
  echo $! > "$UVICORN_PID_FILE"
  echo "App started (pid $(cat "$UVICORN_PID_FILE"))"
  echo "Log: $UVICORN_LOG"
}

stop_app() {
  if [[ -f "$UVICORN_PID_FILE" ]]; then
    local pid
    pid="$(cat "$UVICORN_PID_FILE")"
    if is_pid_running "$pid"; then
      kill "$pid" || true
      echo "App stopped (pid $pid)"
    fi
    rm -f "$UVICORN_PID_FILE"
  else
    echo "App not running"
  fi
}

case "${1:-}" in
  start)
    start_app
    ;;
  stop)
    stop_app
    ;;
  restart)
    stop_app
    start_app
    ;;
  *)
    echo "Usage: $0 {start|stop|restart}"
    exit 2
    ;;
esac
