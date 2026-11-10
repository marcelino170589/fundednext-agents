#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Deteniendo servicios FNL:004"

kill_by_name() {
    local name="$1"
    local pids
    pids=$(pgrep -f "$name" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "  Deteniendo $name (PIDs: $pids)"
        kill $pids 2>/dev/null || true
        sleep 1
        pids=$(pgrep -f "$name" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "  Forzando $name (PIDs: $pids)"
            kill -9 $pids 2>/dev/null || true
        fi
    else
        echo "  $name no está corriendo"
    fi
}

kill_by_name "orchestrator.py"
kill_by_name "htf_pullback_service.py"
kill_by_name "uvicorn api_server"

rm -f logs/*.pid 2>/dev/null || true

echo "✓ Servicios detenidos"
