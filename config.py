# config.py
"""
Configuración completa para FundedNext CFDs-FNL:004 (Instant 50K).
Incluye parámetros de enriquecimiento: correlación, score mínimo,
cazador multi-timeframe, alertas locales.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "si", "sí")


# ══════════════════════════════════════════════════════════════════
# LLM
# ══════════════════════════════════════════════════════════════════
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-flash")
LLM_TEMPERATURE = 0.15

# Router multi-proveedor (ver docs/LLM_ROUTER.md)
LLM_ROUTER_ENABLED = _env_bool("LLM_ROUTER_ENABLED", True)
LLM_PROVIDERS_FILE = os.getenv("LLM_PROVIDERS_FILE", "").strip()
LLM_ROUTER_MAX_ATTEMPTS = int(os.getenv("LLM_ROUTER_MAX_ATTEMPTS", "6"))
LLM_ROUTER_COOLDOWN_SEC = int(os.getenv("LLM_ROUTER_COOLDOWN_SEC", "90"))
LLM_ROUTER_TIMEOUT = float(os.getenv("LLM_ROUTER_TIMEOUT", "40"))
LLM_ROUTER_STATE_FILE = os.getenv(
    "LLM_ROUTER_STATE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "llm_router_state.json"),
)

# ══════════════════════════════════════════════════════════════════
# CUENTA FNL:004 (50K)
# ══════════════════════════════════════════════════════════════════
INITIAL_BALANCE = 50_000.0
MAX_LOSS_USD = 2_000.0
MAX_LOSS_PCT = 0.04
TRAILING_DRAWDOWN = True

BUFFER_USD = 2_100.0
MIN_PROFIT_ABOVE_BUFFER = 800.0
MAX_PAYOUT_USD = 1_200.0
PROFIT_SPLIT = 0.80

# ══════════════════════════════════════════════════════════════════
# LÍMITES OPERATIVOS CONSERVADORES
# ══════════════════════════════════════════════════════════════════
OPERATIONAL_DAILY_LOSS_LIMIT = 0.02   # 2% = $500
OPERATIONAL_MAX_LOSS_LIMIT   = 0.05   # 5% = $1,250
OPERATIONAL_MAX_RISK_OPEN    = 0.005  # 0.5% = $250
RISK_PER_TRADE               = 0.002  # 0.20% = $100
MAX_LOT                      = 0.10

# ══════════════════════════════════════════════════════════════════
# OBJETIVO DE RENTABILIDAD
# ══════════════════════════════════════════════════════════════════
WEEKLY_TARGET_NET    = 450.0
MAX_DAILY_PROFIT_USD = 100.0
HARD_DAILY_CAP       = 150.0

# ══════════════════════════════════════════════════════════════════
# REGLA DEL 40% / CONSISTENCY 20%
# ══════════════════════════════════════════════════════════════════
CONSISTENCY_LIMIT  = 0.20
PENALTY_NEAR_LIMIT = 0.15
WEEKLY_RATIO_WARN  = 0.30

# ══════════════════════════════════════════════════════════════════
# MODO DILUCIÓN
# ══════════════════════════════════════════════════════════════════
DILUTION_ENABLED          = True
DILUTION_ENTRY_RATIO      = 0.15
DILUTION_EXIT_RATIO       = 0.12
DILUTION_TARGET_RATIO     = 0.25
DILUTION_DAILY_FACTOR     = 0.40
DILUTION_MIN_DAILY_USD    = 40.0
DILUTION_MAX_DAYS_WARNING = 10

# ══════════════════════════════════════════════════════════════════
# CALIDAD DE SEÑAL (CONSENSO)
# ══════════════════════════════════════════════════════════════════
MIN_SCORE_CONSENSUS          = 80
MIN_PROBABILITY_CONTINUATION = 70
MIN_DIVERGENCE_INDEX         = 20
MAX_ADVERSARY_GRAVITY        = 6

# ══════════════════════════════════════════════════════════════════
# CAZADOR DE OPORTUNIDADES
# ══════════════════════════════════════════════════════════════════
MIN_CONFLUENCIA      = 2       # Confluencia mínima de estrategias (2+)
SCORE_MINIMO         = 0       # Score mínimo (0 = sin filtro)
FILTRAR_CORRELACION  = True    # Evita trades en pares correlacionados
MAX_POR_GRUPO_CORR   = 1       # Máximo de trades por grupo de correlación
HUNTER_TOP_N         = 5       # Top N oportunidades a notificar

# ══════════════════════════════════════════════════════════════════
# FILTROS OPERATIVOS
# ══════════════════════════════════════════════════════════════════
NEWS_BLACKOUT_MIN       = 15
MIN_TRADE_DURATION_MIN  = 5
MAX_CONSECUTIVE_LOSSES  = 3
COOLDOWN_AFTER_LOSSES_H = 2

# ══════════════════════════════════════════════════════════════════
# HORARIO (UTC)
# ══════════════════════════════════════════════════════════════════
SESSION_ENABLED = True
SESSION_START_UTC = 7
SESSION_END_UTC = 21
NO_OPERATE_FRIDAY_AFTER_UTC = 18

# Símbolos que requieren sesión específica
SYMBOLS_SESSION_ONLY = {
    "XAUUSD": (7, 21),
    "XAGUSD": (7, 21),
    "XPTUSD": (7, 21),
    "UKOUSD": (7, 21),
    "USOUSD": (7, 21),
    # Índices: cada uno en su sesión natural
    "SPX500": (13, 21),   # NY
    "NDX100": (13, 21),   # NY
    "US30":   (13, 21),   # NY
    "US2000": (13, 21),   # NY
    "GER30":  (7, 16),    # Frankfurt
    "UK100":  (7, 16),    # Londres
    "FRA40":  (7, 16),    # París
    "EUSTX50":(7, 16),    # Europa
    "SWI20":  (7, 16),    # Zúrich
    "JP225":  (0, 6),     # Tokio
    "HK50":   (1, 8),     # Hong Kong
    "AUS200": (22, 6),    # Sídney
}

# ══════════════════════════════════════════════════════════════════
# SÍMBOLOS PRINCIPALES (los que analiza el consenso de 9 capas)
# ══════════════════════════════════════════════════════════════════
# El CAZADOR escanea TODOS los símbolos de symbol_config.py,
# pero el CONSENSO de 9 capas analiza solo estos 4 pares principales.
SYMBOLS = ["XAUUSD", "USDJPY", "EURUSD", "USDCAD"]

# ══════════════════════════════════════════════════════════════════
# ZMQ (WireGuard: VPS=172.29.31.217, PC=172.29.16.1)
# ══════════════════════════════════════════════════════════════════
ZMQ_SIGNAL_PORT = 5555
ZMQ_STATE_PORT  = 5556
ZMQ_OHLC_PORT   = 5557
ZMQ_VPS_IP = "172.29.31.217"
ZMQ_PC_IP  = "172.29.16.1"

# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_ENABLED = _env_bool("TELEGRAM_ENABLED", False)
TELEGRAM_MIN_SEVERITY = os.getenv("TELEGRAM_MIN_SEVERITY", "INFO").strip().upper()
TELEGRAM_RATE_LIMIT_SECONDS = float(os.getenv("TELEGRAM_RATE_LIMIT_SECONDS", "1.5"))
TELEGRAM_DEDUPE_SECONDS = int(os.getenv("TELEGRAM_DEDUPE_SECONDS", "300"))
TELEGRAM_MAX_CHARS = int(os.getenv("TELEGRAM_MAX_CHARS", "3900"))

SEVERITY_LEVELS = {"INFO": 1, "WARNING": 2, "CRITICAL": 3}
# ══════════════════════════════════════════════════════════════════
# EA HUMANIZACIÓN
# ══════════════════════════════════════════════════════════════════
HUMANIZE_ENABLED = True
DELAY_MIN_MS     = 3000
DELAY_MAX_MS     = 10000
LOT_VARIANCE_PCT = 4.0
TICK_NOISE_MAX   = 1
SKIP_ONE_EVERY_N = 10
BLANK_COMMENT    = True
SEED_MODE        = 3  # ACCOUNT_HASH
