#!/usr/bin/env bash
# Arranca todos los servicios en background (para WSL/Linux local)
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null || { echo "✗ venv no encontrado"; exit 1; }

LOG="logs"
mkdir -p "$LOG"

echo "═══════════════════════════════════════════════════════"
echo "  Arrancando servicios FNL:004 (local)"
echo "═══════════════════════════════════════════════════════"

for f in orchestrator.py api_server.py htf_pullback_service.py; do
    [[ -f "$f" ]] || { echo "✗ Falta $f"; exit 1; }
done

nohup python orchestrator.py > "$LOG/orchestrator.out" 2>&1 &
echo $! > "$LOG/orchestrator.pid"
echo "✓ Orquestador PID: $(cat $LOG/orchestrator.pid)"

nohup python htf_pullback_service.py > "$LOG/htf.out" 2>&1 &
echo $! > "$LOG/htf.pid"
echo "✓ HTF PID: $(cat $LOG/htf.pid)"

nohup python -m uvicorn api_server:app --host 127.0.0.1 --port 8000 \
    > "$LOG/api.out" 2>&1 &
echo $! > "$LOG/api.pid"
echo "✓ API PID: $(cat $LOG/api.pid)"

sleep 2
echo ""
echo "Dashboard:  http://localhost:8000"
echo "Logs:       tail -f $LOG/orchestrator.out"
echo "Detener:    ./stop_all.sh"