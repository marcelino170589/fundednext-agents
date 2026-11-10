# strategies/mtf_alignment.py
"""
Estrategia de Alineación Multi-Timeframe (MTF).
Detecta patrones de retroceso entre H4, H1, M15 y M5.
"""
from statistics import mean


def _ema(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _atr(velas, period=14):
    if len(velas) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["high"], velas[i]["low"], velas[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return mean(trs[-period:])


def _direccion_tf(velas, ema_period=20):
    if len(velas) < ema_period + 3:
        return "NEUTRAL"
    closes = [v["close"] for v in velas]
    ema = _ema(closes, ema_period)
    if len(ema) < 3:
        return "NEUTRAL"
    precio_actual = closes[-1]
    ema_actual = ema[-1]
    ema_anterior = ema[-3]
    pendiente = ema_actual - ema_anterior
    if precio_actual > ema_actual and pendiente > 0:
        return "LONG"
    if precio_actual < ema_actual and pendiente < 0:
        return "SHORT"
    return "NEUTRAL"


def _direccion_vela(vela):
    if vela["close"] > vela["open"]:
        return "LONG"
    if vela["close"] < vela["open"]:
        return "SHORT"
    return "NEUTRAL"


def detectar_patron_mtf(velas_por_tf, symbol):
    h4 = velas_por_tf.get("H4", [])
    h1 = velas_por_tf.get("H1", [])
    m15 = velas_por_tf.get("M15", [])
    m5 = velas_por_tf.get("M5", [])

    if not all([len(h4) >= 60, len(h1) >= 60, len(m15) >= 60, len(m5) >= 60]):
        return None

    dir_h4 = _direccion_tf(h4, 20)
    dir_h1 = _direccion_tf(h1, 20)
    dir_m15 = _direccion_tf(m15, 20)
    dir_m5 = _direccion_tf(m5, 20)

    # PATRÓN A: H4+H1 alineados, M15+M5 en contra
    if dir_h4 == dir_h1 and dir_h4 != "NEUTRAL":
        if dir_m15 == dir_m5 and dir_m15 != "NEUTRAL" and dir_m15 != dir_h4:
            vela_m5 = m5[-1]
            dir_vela_m5 = _direccion_vela(vela_m5)
            if dir_vela_m5 == dir_h4:
                entry = vela_m5["close"]
                atr_h1 = _atr(h1, 14)
                if atr_h1 <= 0:
                    return None
                if dir_h4 == "LONG":
                    sl = entry - atr_h1 * 1.5
                    risk = entry - sl
                    tp = entry + risk * 2.0
                else:
                    sl = entry + atr_h1 * 1.5
                    risk = sl - entry
                    tp = entry - risk * 2.0
                return {
                    "patron": "MTF_A_retroceso_H1",
                    "direccion": dir_h4,
                    "entry": round(entry, 5),
                    "sl": round(sl, 5),
                    "tp": round(tp, 5),
                    "tf_tendencia": "H4",
                    "tf_retroceso": "H1",
                    "tf_trigger": "M5",
                    "direcciones": {"H4": dir_h4, "H1": dir_h1, "M15": dir_m15, "M5": dir_m5},
                    "confidence": 80,
                    "reason": f"H4+H1 {dir_h4}, M15+M5 en contra, M5 giró a favor",
                }

    # PATRÓN B: H1+M15+M5 en contra de H4
    if dir_h4 != "NEUTRAL":
        contra = [d for d in (dir_h1, dir_m15, dir_m5) if d != "NEUTRAL" and d != dir_h4]
        if len(contra) == 3:
            vela_h4 = h4[-1]
            dir_vela_h4 = _direccion_vela(vela_h4)
            if dir_vela_h4 == dir_h4:
                entry = vela_h4["close"]
                atr_h4 = _atr(h4, 14)
                if atr_h4 <= 0:
                    return None
                if dir_h4 == "LONG":
                    sl = entry - atr_h4 * 1.5
                    risk = entry - sl
                    tp = entry + risk * 2.5
                else:
                    sl = entry + atr_h4 * 1.5
                    risk = sl - entry
                    tp = entry - risk * 2.5
                return {
                    "patron": "MTF_B_retroceso_H4",
                    "direccion": dir_h4,
                    "entry": round(entry, 5),
                    "sl": round(sl, 5),
                    "tp": round(tp, 5),
                    "tf_tendencia": "H4",
                    "tf_retroceso": "H4",
                    "tf_trigger": "H4",
                    "direcciones": {"H4": dir_h4, "H1": dir_h1, "M15": dir_m15, "M5": dir_m5},
                    "confidence": 85,
                    "reason": f"H1+M15+M5 en contra de H4, nueva vela H4 confirma {dir_h4}",
                }

    return None


def run(velas_por_tf, symbol, cfg):
    resultado = detectar_patron_mtf(velas_por_tf, symbol)
    if not resultado:
        return None
    return {
        "strategy": "mtf_alignment",
        "timeframe": "H4",
        "direction": resultado["direccion"],
        "entry": resultado["entry"],
        "sl": resultado["sl"],
        "tp": resultado["tp"],
        "confidence": resultado["confidence"],
        "reason": resultado["reason"],
        "patron": resultado["patron"],
        "direcciones_tf": resultado["direcciones"],
        "stop_atr": 1.5,
        "trailing_atr": 2.0,
    }
