#!/usr/bin/env bash
# Tek tuşla demo (Linux/macOS/Git Bash): ./run.sh [fixture|simulator]
set -euo pipefail
MODE=${1:-simulator}; API_PORT=${API_PORT:-8000}; SIM_PORT=${SIM_PORT:-8081}
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || PY=python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export NAC_MODE=$MODE
export PUBLIC_BASE_URL=${PUBLIC_BASE_URL:-http://127.0.0.1:$API_PORT}
SIM_PID=""
if [ "$MODE" = "simulator" ]; then
  export NAC_BASE_URL="http://127.0.0.1:$SIM_PORT"
  "$PY" -m uvicorn arrivalguard.simulator.app:app --port "$SIM_PORT" --log-level warning &
  SIM_PID=$!
  trap '[ -n "$SIM_PID" ] && kill "$SIM_PID" 2>/dev/null' EXIT
  sleep 1
fi
echo "Demo:    http://127.0.0.1:$API_PORT/demo"
echo "Konsol:  http://127.0.0.1:$API_PORT/console   API belgesi: /docs   mode=$MODE"
"$PY" -m uvicorn arrivalguard.api.app:create_app --factory --port "$API_PORT"
