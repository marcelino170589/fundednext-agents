# agents/agent_htf_pullback.py
from llm_client import ask_json
from prompt_rotator import get_prompt

SYSTEM = """Analista de estructura HTF. Distingues retroceso saludable vs reversión.

FNL:004: probabilidad de continuación ≥70% para ENTER_WITH_TREND.

Responde SOLO JSON:
{"symbol":"...","retroceso_saludable":true|false,
 "reversion_probable":true|false,"probabilidad_continuacion":0-100,
 "calidad_entrada":0-100,
 "recomendacion":"WAIT|ENTER_WITH_TREND|AVOID|REVERSAL_WATCH",
 "zona_objetivo_preferida":"ema20|ema50|fib_38_2|fib_50|fib_61_8|pivot",
 "razon":"máx 60 palabras"}"""

def run(estructura):
    symbol = estructura.get("symbol", "XAUUSD")
    system, variant = get_prompt("htf_pullback", symbol)
    if not system:
        system = SYSTEM
    h1 = estructura.get("h1", {})
    h4 = estructura.get("h4", {})
    user = (f"Par: {symbol}\n"
            f"Alineados: {estructura.get('timeframes_aligned')}\n"
            f"H4: {h4.get('trend_direction')} / {h4.get('state')}\n"
            f"H1: {h1.get('trend_direction')} / {h1.get('state')}\n"
            f"Retroceso H1: {h1.get('pullback', {}).get('retracement_pct', '—')}%\n"
            f"Zona clave: {h1.get('pullback', {}).get('near_key_zone')}\n"
            f"Rechazo: {h1.get('pullback', {}).get('rejection_candle')}")
    out = ask_json(system, user)
    out["_variant"] = variant
    return out