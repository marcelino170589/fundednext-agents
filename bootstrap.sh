#!/usr/bin/env bash
set -euo pipefail

mkdir -p fundednext_agents/{agents,strategies,static,MQL5,systemd,data,logs,logs/archive,backups}

touch fundednext_agents/agents/__init__.py
touch fundednext_agents/strategies/__init__.py

cat > fundednext_agents/.gitignore <<'EOF'
venv/
__pycache__/
*.pyc
.env
data/*.db
data/*.db-*
data/*.json
logs/*.log
logs/*.jsonl
backups/*
!backups/.gitkeep
EOF

echo "✓ Estructura creada:"
find fundednext_agents -type d | sort
echo ""
echo "Ahora copia todos los .py de Chunks 1-4 + carpetas agents/ strategies/ static/ MQL5/ systemd/"