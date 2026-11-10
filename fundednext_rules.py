# fundednext_rules.py
"""Reglas FNL:004 + validaciones ultra-conservadoras."""
from config import (
    INITIAL_BALANCE, MAX_LOSS_USD, OPERATIONAL_MAX_RISK_OPEN,
    RISK_PER_TRADE, MAX_DAILY_PROFIT_USD, HARD_DAILY_CAP,
    MAX_LOT, NEWS_BLACKOUT_MIN,
)


def pip_size(symbol: str) -> float:
    if symbol.upper().startswith(("XAU", "XAG")):
        return 0.01
    if "JPY" in symbol.upper():
        return 0.01
    return 0.0001


def pip_value_per_lot(symbol: str) -> float:
    s = symbol.upper()
    if s.startswith("XAU"):
        return 1.0
    if s.startswith("XAG"):
        return 5.0
    if "JPY" in s:
        return 6.8
    return 10.0


def calc_lotage(symbol: str, entry: float, sl: float,
                balance: float = INITIAL_BALANCE) -> float:
    """Calcula lotaje para arriesgar RISK_PER_TRADE (0.25% = $125)."""
    distancia = abs(entry - sl)
    if distancia <= 0:
        return 0.0
    pips = distancia / pip_size(symbol)
    valor_pip = pip_value_per_lot(symbol)
    riesgo_usd = balance * RISK_PER_TRADE  # $125
    lotaje = riesgo_usd / (pips * valor_pip)
    lotaje = round(max(lotaje, 0.01), 2)
    return min(lotaje, MAX_LOT)


def validar_orden_fnl004(signal: dict, state: dict,
                          profit_tracker=None) -> tuple[bool, str]:
    """
    Validación para FNL:004.
    - Sin Daily Loss Limit oficial.
    - Usamos límite operativo conservador sobre riesgo abierto.
    - Verificamos trailing drawdown (el estado debe traer el pico de equity).
    """
    symbol = signal.get("activo", "")
    entry = float(signal.get("entrada", 0))
    sl = float(signal.get("sl", 0))
    lotaje = float(signal.get("lotaje", 0))

    if not symbol or entry <= 0 or sl <= 0 or lotaje <= 0:
        return False, "Señal inválida"

    if lotaje > MAX_LOT:
        return False, f"Lotaje {lotaje} > MAX_LOT {MAX_LOT}"

    # ── Trailing Drawdown (CRÍTICO) ──
    # El límite inferior sube con el pico de equity. El estado debe
    # tener 'peak_equity' y 'trailing_floor' calculados por el orquestador.
    peak = state.get("peak_equity", INITIAL_BALANCE)
    trailing_floor = max(INITIAL_BALANCE - MAX_LOSS_USD, peak - MAX_LOSS_USD)
    equity = state.get("equity", INITIAL_BALANCE)

    riesgo_orden = abs(entry - sl) / pip_size(symbol) * pip_value_per_lot(symbol) * lotaje
    if equity - riesgo_orden < trailing_floor:
        return False, f"Trailing drawdown: equity {equity:.0f} - riesgo {riesgo_orden:.0f} < floor {trailing_floor:.0f}"

    # ── Riesgo abierto operativo (0.5% = $250, vs $2,000 oficial) ──
    max_risk_op = INITIAL_BALANCE * OPERATIONAL_MAX_RISK_OPEN  # $250
    riesgo_actual = state.get("riesgo_abierto", 0)
    if riesgo_actual + riesgo_orden > max_risk_op:
        return False, f"Riesgo abierto operativo (${riesgo_actual + riesgo_orden:.0f} > ${max_risk_op})"

    # ── Objetivo diario ──
    if profit_tracker:
        if profit_tracker.objetivo_alcanzado():
            return False, "Objetivo diario alcanzado"
        if profit_tracker.daily_pnl_hoy() >= HARD_DAILY_CAP:
            return False, f"Tope duro diario (${HARD_DAILY_CAP})"

    # ── Duración mínima ──
    if signal.get("duracion_estimada_min", 0) < 5:
        return False, "Duración < 5 min (quick strike)"

    return True, "OK"