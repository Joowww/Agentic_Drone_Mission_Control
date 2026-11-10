#!/usr/bin/env bash
# Separate Ollama server for the local Hermes demo, so the system Ollama service keeps its own settings.
#
#   deploy/hermes_local_demo/ollama_demo_instance.sh start|status|stop
#
# It listens on loopback only (127.0.0.1:11435 by default) with flash attention and a q4_0 KV cache: on an
# 8 GiB GPU this is what lets a 4B model with Hermes' minimum context (64 000 tokens) fit entirely on the GPU
# (measured 08/11/2026: evaluation/observability/ollama_context_memory_2026_11_08). It reads the models of the
# installed Ollama (OLLAMA_MODELS) and never prunes them. State (pid, log) goes to a private directory.
set -euo pipefail

PORT="${TFG_DEMO_OLLAMA_PORT:-11435}"
STATE="${TFG_DEMO_OLLAMA_STATE:-$HOME/tfg-local-demo/ollama}"
if [[ -z "${OLLAMA_MODELS:-}" ]]; then
  if [[ -d /usr/share/ollama/.ollama/models ]]; then OLLAMA_MODELS=/usr/share/ollama/.ollama/models
  else OLLAMA_MODELS="$HOME/.ollama/models"; fi
fi
PID_FILE="$STATE/serve.pid"
URL="http://127.0.0.1:$PORT"

running_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid; pid="$(cat "$PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ ]] && [[ -r "/proc/$pid/cmdline" ]] || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "ollama serve" || return 1
  echo "$pid"
}

case "${1:-}" in
  start)
    if pid="$(running_pid)"; then echo "already running (pid $pid) at $URL"; exit 0; fi
    if curl -s --max-time 2 "$URL/api/version" >/dev/null; then
      echo "port $PORT is already in use by another process; not starting" >&2; exit 1
    fi
    mkdir -p -m 700 "$STATE"
    OLLAMA_HOST="127.0.0.1:$PORT" OLLAMA_MODELS="$OLLAMA_MODELS" OLLAMA_FLASH_ATTENTION=1 \
      OLLAMA_KV_CACHE_TYPE=q4_0 OLLAMA_NOPRUNE=1 OLLAMA_KEEP_ALIVE=30m \
      setsid nohup ollama serve >> "$STATE/serve.log" 2>&1 &
    echo $! > "$PID_FILE"
    for _ in $(seq 1 30); do
      if curl -s --max-time 2 "$URL/api/version" >/dev/null; then
        echo "started (pid $(cat "$PID_FILE")) at $URL; models from $OLLAMA_MODELS; log $STATE/serve.log"; exit 0
      fi
      sleep 1
    done
    echo "did not answer within 30 s; see $STATE/serve.log" >&2; exit 1 ;;
  status)
    if pid="$(running_pid)"; then echo "running (pid $pid) at $URL"; else echo "not running"; fi
    curl -s --max-time 2 "$URL/api/version" && echo
    OLLAMA_HOST="127.0.0.1:$PORT" ollama ps || true ;;
  stop)
    if pid="$(running_pid)"; then kill "$pid"; rm -f "$PID_FILE"; echo "stopped (pid $pid)"
    else echo "not running (nothing stopped)"; fi ;;
  *)
    echo "usage: $0 start|status|stop" >&2; exit 2 ;;
esac
