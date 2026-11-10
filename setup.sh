#!/usr/bin/env bash
# setup.sh — Instalador para WSL/Linux local
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/setup.env"
LOG="$SCRIPT_DIR/install.log"
APP_HOME="$SCRIPT_DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok(){ echo -e "${GREEN}✓${NC} $*"|tee -a "$LOG"; }
warn(){ echo -e "${YELLOW}⚠${NC} $*"|tee -a "$LOG"; }
err(){ echo -e "${RED}✗${NC} $*"|tee -a "$LOG"; }
die(){ err "$*"; exit 1; }

[[ ! -f "$ENV_FILE" ]] && die "Falta setup.env en $SCRIPT_DIR"
source "$ENV_FILE"

echo "Instalación local iniciada: $(date)" > "$LOG"

# 1. Dependencias del sistema
ok "Verificando dependencias..."
command -v python3 >/dev/null || die "python3 no instalado"
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" \
    || die "Python >= 3.10 requerido"
ok "Python $(python3 --version | awk '{print $2}')"

# 2. Estructura
mkdir -p data logs logs/archive backups static systemd strategies agents
ok "Estructura creada"

# 3. Venv
if [[ ! -d venv ]]; then
    python3 -m venv venv
    ok "Venv creado"
fi
source venv/bin/activate
pip install -q --upgrade pip wheel setuptools
[[ -f requirements.txt ]] && pip install -q -r requirements.txt
ok "Dependencias Python instaladas"

# 4. .env
if [[ ! -f .env ]]; then
    cat > .env <<EOF
LLM_API_KEY=$LLM_API_KEY
LLM_BASE_URL=$LLM_BASE_URL
LLM_MODEL=$LLM_MODEL
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
TELEGRAM_ENABLED=$TELEGRAM_ENABLED
EOF
    chmod 600 .env
    ok ".env creado"
else
    warn ".env ya existe, no se sobreescribe"
fi

# 5. DB
python -c "import journal; journal.init_db(); print('DB lista')" 2>/dev/null || warn "DB pendiente"

# 6. Verificación
ok "Verificación final:"
for f in orchestrator.py consensus_v2.py fundednext_rules.py profit_tracker.py \
         journal.py api_server.py notifier.py scheduler.py; do
    [[ -f "$f" ]] && ok "  $f" || warn "  $f FALTA"
done

echo ""
ok "Instalación completa"
echo ""
echo "Siguiente:"
echo "  1. Edita .env con tu API key de DeepSeek"
echo "  2. Arranca: ./start_all.sh"
echo "  3. Verifica: http://localhost:8000"
echo "  4. En MT5 (Windows): compila MQL5/OrchestratorEA.mq5"
echo "     - ZMQ_PYTHON_HOST = tcp://127.0.0.1"
echo "     - ZMQ_LOCAL_BIND  = tcp://127.0.0.1"