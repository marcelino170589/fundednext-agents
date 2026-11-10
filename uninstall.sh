#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════"
echo "  DESINSTALAR FUNDEDNEXT AGENTS"
echo "═══════════════════════════════════════════════════════"
echo ""

# Primero detener servicios
./stop_all.sh 2>/dev/null || true
echo ""

echo "Esto eliminará:"
echo "  - venv/"
echo "  - data/ (incluye journal.db)"
echo "  - logs/"
echo "  - backups/"
echo "  - .env"
echo ""
read -p "Escribe SI para confirmar: " c

if [ "$c" != "SI" ]; then
    echo "Cancelado. Solo se detuvieron los servicios."
    exit 0
fi

# Backup de DB antes de borrar
if [ -f data/journal.db ]; then
    cp data/journal.db "backup_journal_$(date +%Y%m%d_%H%M%S).db"
    echo "✓ Backup de journal.db creado"
fi

rm -rf venv data logs backups .env
echo "✓ Desinstalación completa"
