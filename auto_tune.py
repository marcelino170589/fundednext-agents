# auto_tune.py
"""Auto-ajuste de umbrales por régimen de volatilidad."""
import json, os
from datetime import datetime
from symbol_config import get_config, supported_symbols

TUNE_FILE = "data/tuned_thresholds.json"


def _pcts(vals, puntos):
    s = sorted(vals)
    return {p: s[int(p / 100 * (len(s) - 1))] for p in puntos} if s else {p: 0 for p in puntos}


def tune_symbol(symbol, velas_h1):
    from htf_structure_v2 import _atr
    cfg = get_config(symbol)
    if not cfg or len(velas_h1) < 200: return None
    atrs = []
    for i in range(20, len(velas_h1)):
        a = _atr(velas_h1[i - 20:i + 1], cfg.atr_period)
        if a > 0: atrs.append(a)
    if len(atrs) < 100: return None
    p = _pcts(atrs, [10, 25, 50, 75, 90])
    actual = atrs[-1]
    if actual >= p[90]: factor, regime = 1.30, "very_high_vol"
    elif actual >= p[75]: factor, regime = 1.15, "high_vol"
    elif actual >= p[25]: factor, regime = 1.00, "normal_vol"
    elif actual >= p[10]: factor, regime = 0.85, "low_vol"
    else: factor, regime = 0.70, "very_low_vol"
    return {"symbol": symbol, "tuned_at": datetime.utcnow().isoformat(),
            "regime": regime, "factor": factor,
            "min_atr_impulse": round(cfg.min_atr_impulse * factor, 2),
            "min_pullback_pct": round(cfg.min_pullback_pct * factor, 1),
            "max_pullback_pct": cfg.max_pullback_pct,
            "key_zone_tolerance_pct": round(cfg.key_zone_tolerance_pct * factor, 2)}


def update(hist):
    os.makedirs("data", exist_ok=True)
    result = {}
    for sym in supported_symbols():
        t = tune_symbol(sym, hist.get(sym, []))
        if t: result[sym] = t
    with open(TUNE_FILE, "w") as f:
        json.dump({"updated_at": datetime.utcnow().isoformat(), "symbols": result}, f, indent=2)
    return result


def get_effective(symbol):
    cfg = get_config(symbol)
    if not cfg: return {}
    if os.path.exists(TUNE_FILE):
        try:
            with open(TUNE_FILE) as f:
                t = json.load(f).get("symbols", {}).get(symbol)
            if t:
                return {"min_atr_impulse": t["min_atr_impulse"],
                        "min_pullback_pct": t["min_pullback_pct"],
                        "max_pullback_pct": t["max_pullback_pct"],
                        "key_zone_tolerance_pct": t["key_zone_tolerance_pct"],
                        "regime": t["regime"], "source": "tuned"}
        except Exception: pass
    return {"min_atr_impulse": cfg.min_atr_impulse,
            "min_pullback_pct": cfg.min_pullback_pct,
            "max_pullback_pct": cfg.max_pullback_pct,
            "key_zone_tolerance_pct": cfg.key_zone_tolerance_pct,
            "regime": "default", "source": "config"}