# agents/agent_strategies.py
"""Agente de estrategias clásicas (sin LLM)."""
from strategies.catalog import evaluar_todas
from symbol_config import get_config


def run(symbol, velas_por_tf):
    cfg = get_config(symbol)
    if not cfg:
        return {"strategy": "catalog", "signals": [], "consensus": None}

    todas = []
    for tf, velas in velas_por_tf.items():
        if not velas:
            continue
        try:
            todas.extend(evaluar_todas(symbol, tf, velas, cfg.__dict__))
        except Exception:
            continue

    if not todas:
        return {"strategy": "catalog", "signals": [], "consensus": None}

    longs = sum(1 for s in todas if s["direction"] == "LONG")
    shorts = sum(1 for s in todas if s["direction"] == "SHORT")

    if longs == shorts:
        return {"strategy": "catalog", "signals": todas, "consensus": None}

    direction = "LONG" if longs > shorts else "SHORT"
    confianza = min(90, 50 + (max(longs, shorts) / len(todas)) * 40)
    mejor = max(todas, key=lambda s: s.get("confidence", 0))

    return {"strategy": "catalog", "signals": todas,
            "consensus": {"direction": direction, "confidence": round(confianza, 1),
                          "entry": mejor["entry"], "sl": mejor["sl"],
                          "tp": mejor["tp"], "count": len(todas),
                          "used_strategy": mejor["strategy"],
                          "timeframe": mejor["timeframe"]}}