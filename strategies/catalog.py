# strategies/catalog.py
"""
Catálogo de estrategias clásicas validadas con backtest.
- Fozzy (RSI8 + EMA8) → XAUUSD, USDJPY
- Turtle (Donchian 20/10) → USDJPY, USDCAD, XAUUSD
- Larry Williams (%R + MA10) → XAUUSD, USDJPY, EURUSD
- HTF Pullback → todos
- MTF Alignment → todos
- Bollinger Breakout → todos
- RSI Divergence → todos
- MA Crossover → todos
- MACD Signal → todos
"""
from statistics import mean

from strategies.extra_indicators import (
    bollinger_breakout, rsi_divergence, ma_crossover, macd_signal,
)
from strategies.trullas import trullas_macd_triple_divergence


def ema(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    r = [sum(values[:period]) / period]
    for v in values[period:]:
        r.append(v * k + r[-1] * (1 - k))
    return r


def rsi(values, period=8):
    if len(values) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag, al = mean(gains[:period]), mean(losses[:period])
    res = []
    for i in range(period, len(gains) + 1):
        if i > period:
            ag = (ag * (period - 1) + gains[i - 1]) / period
            al = (al * (period - 1) + losses[i - 1]) / period
        res.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return res


def atr(velas, period=20):
    if len(velas) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["high"], velas[i]["low"], velas[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return mean(trs[-period:])


def williams_r(velas, period=14):
    if len(velas) < period:
        return []
    result = []
    for i in range(period - 1, len(velas)):
        window = velas[i - period + 1:i + 1]
        hh = max(v["high"] for v in window)
        ll = min(v["low"] for v in window)
        close = velas[i]["close"]
        if hh == ll:
            result.append(-50.0)
        else:
            result.append(-100 * (hh - close) / (hh - ll))
    return result


# ═══════════════════════════════════════════════════════════════
# FOZZY
# ═══════════════════════════════════════════════════════════════
def fozzy(velas, symbol, cfg):
    if symbol.upper() not in ("XAUUSD", "USDJPY"):
        return None
    if len(velas) < 60:
        return None

    closes = [v["close"] for v in velas]
    r = rsi(closes, 8)
    if len(r) < 10:
        return None
    re = ema(r, 8)
    if len(re) < 3:
        return None

    off = len(r) - len(re)
    ra = r[off:]
    if len(ra) < 2:
        return None

    cruz_alc = ra[-2] <= re[-2] and ra[-1] > re[-1]
    cruz_baj = ra[-2] >= re[-2] and ra[-1] < re[-1]
    if not (cruz_alc or cruz_baj):
        return None

    d = "LONG" if cruz_alc else "SHORT"
    e = velas[-1]["close"]

    if len(closes) >= 50:
        ma10w = mean(closes[-50:])
        if d == "LONG" and e < ma10w:
            return None
        if d == "SHORT" and e > ma10w:
            return None

    a = atr(velas, 20)
    if a <= 0:
        return None

    sl = e - a * 2.0 if d == "LONG" else e + a * 2.0
    risk = abs(e - sl)
    tp = e + risk * 1.5 if d == "LONG" else e - risk * 1.5

    return {
        "strategy": "fozzy_8_8", "timeframe": "D1", "direction": d,
        "entry": e, "sl": round(sl, 5), "tp": round(tp, 5),
        "confidence": 75, "reason": "RSI(8) cruce + MA10",
        "stop_atr": 2.0, "trailing_atr": 3.0,
    }


# ═══════════════════════════════════════════════════════════════
# TURTLE
# ═══════════════════════════════════════════════════════════════
def turtle(velas, symbol, cfg):
    if symbol.upper() not in ("USDJPY", "USDCAD", "XAUUSD"):
        return None
    if len(velas) < 25:
        return None

    lb = 20
    hs = [v["high"] for v in velas[-lb - 1:-1]]
    ls = [v["low"] for v in velas[-lb - 1:-1]]
    if not hs or not ls:
        return None

    c = velas[-1]["close"]
    a = atr(velas, 20)
    if a <= 0:
        return None

    if c > max(hs):
        d, e = "LONG", c
        sl, tp = e - a * 2, e + a * 4
    elif c < min(ls):
        d, e = "SHORT", c
        sl, tp = e + a * 2, e - a * 4
    else:
        return None

    return {
        "strategy": "turtle_donchian_20", "timeframe": "D1", "direction": d,
        "entry": e, "sl": round(sl, 5), "tp": round(tp, 5),
        "confidence": 72, "reason": "Ruptura Donchian(20)",
        "stop_atr": 2.0, "trailing_atr": 3.0,
    }


# ═══════════════════════════════════════════════════════════════
# LARRY WILLIAMS
# ═══════════════════════════════════════════════════════════════
def larry(velas, symbol, cfg):
    if symbol.upper() not in ("XAUUSD", "USDJPY", "EURUSD"):
        return None
    if len(velas) < 60:
        return None

    closes = [v["close"] for v in velas]
    wr = williams_r(velas, 14)
    if len(wr) < 3:
        return None
    if len(closes) < 50:
        return None

    ma10w = mean(closes[-50:])
    wr_prev = wr[-2]
    wr_curr = wr[-1]
    close = closes[-1]

    if close > ma10w and wr_prev < -80 and wr_curr >= -80:
        direction = "LONG"
    elif close < ma10w and wr_prev > -20 and wr_curr <= -20:
        direction = "SHORT"
    else:
        return None

    a = atr(velas, 20)
    if a <= 0:
        return None

    entry = close
    sl = entry - a * 2.0 if direction == "LONG" else entry + a * 2.0
    risk = abs(entry - sl)
    tp = entry + risk * 1.5 if direction == "LONG" else entry - risk * 1.5

    return {
        "strategy": "larry_williams", "timeframe": "D1", "direction": direction,
        "entry": entry, "sl": round(sl, 5), "tp": round(tp, 5),
        "confidence": 78, "reason": f"Williams %R={wr_curr:.1f} + MA10",
        "stop_atr": 2.0, "trailing_atr": 3.0,
    }


# ═══════════════════════════════════════════════════════════════
# ORDER FLOW
# ═══════════════════════════════════════════════════════════════
def order_flow(velas, symbol, cfg):
    if len(velas) < 10:
        return None
    vols = [v.get("volume", v["high"] - v["low"]) for v in velas[-10:]]
    mv = mean(vols[:-1])
    if mv <= 0:
        return None
    l = velas[-1]
    body = abs(l["close"] - l["open"])
    rng = l["high"] - l["low"]
    if rng <= 0 or body / rng < 0.7 or vols[-1] < mv * 1.5:
        return None
    d = "LONG" if l["close"] > l["open"] else "SHORT"
    e = l["close"]
    if d == "LONG":
        sl = l["low"] - rng * 0.1
        risk = e - sl
        tp = e + risk * 3
    else:
        sl = l["high"] + rng * 0.1
        risk = sl - e
        tp = e - risk * 3
    return {"strategy": "order_flow", "timeframe": "M15",
            "direction": d, "entry": e, "sl": round(sl, 5),
            "tp": round(tp, 5), "confidence": 55,
            "reason": "Volumen desequilibrio"}


# ═══════════════════════════════════════════════════════════════
# RSI2 + BOLLINGER
# ═══════════════════════════════════════════════════════════════
def rsi2_bb(velas, symbol, cfg):
    if len(velas) < 25:
        return None
    closes = [v["close"] for v in velas]
    r = rsi(closes, 2)
    if len(r) < 2:
        return None
    rr = r[-1]
    m = mean(closes[-20:])
    sd = (sum((c - m) ** 2 for c in closes[-20:]) / 20) ** 0.5
    up, lo = m + 2 * sd, m - 2 * sd
    c = closes[-1]
    a = atr(velas, 14)
    if a <= 0:
        return None
    if rr < 5 and c <= lo:
        d, e = "LONG", c
        sl, tp = e - a * 1.5, e + a * 2.25
    elif rr > 95 and c >= up:
        d, e = "SHORT", c
        sl, tp = e + a * 1.5, e - a * 2.25
    else:
        return None
    return {"strategy": "rsi2_bollinger", "timeframe": "H1",
            "direction": d, "entry": e, "sl": round(sl, 5),
            "tp": round(tp, 5), "confidence": 58,
            "reason": f"RSI(2)={rr:.1f}"}


# ═══════════════════════════════════════════════════════════════
# CATÁLOGO
# ═══════════════════════════════════════════════════════════════
CATALOG = {
    "fozzy_8_8": {"fn": fozzy, "timeframes": ["D1"]},
    "turtle_donchian_20": {"fn": turtle, "timeframes": ["D1"]},
    "larry_williams": {"fn": larry, "timeframes": ["D1"]},
    "bollinger_breakout": {"fn": bollinger_breakout, "timeframes": ["D1", "H4"]},
    "rsi_divergence": {"fn": rsi_divergence, "timeframes": ["H1", "H4"]},
    "ma_crossover": {"fn": ma_crossover, "timeframes": ["D1", "H4"]},
    "macd_signal": {"fn": macd_signal, "timeframes": ["H1", "H4", "D1"]},
    "order_flow_imbalance": {"fn": order_flow, "timeframes": ["M15", "H1"]},
    "rsi2_bollinger": {"fn": rsi2_bb, "timeframes": ["H1", "H4"]},
    "trullas_macd_triple_divergence": {
        "fn": trullas_macd_triple_divergence,
        "timeframes": ["M5", "M15", "H1", "H4"],
    },
}


def evaluar_todas(symbol, timeframe, velas, cfg):
    señales = []
    for name, meta in CATALOG.items():
        if timeframe not in meta["timeframes"]:
            continue
        if name == "mtf_alignment":
            continue
        if not isinstance(velas, list):
            continue
        try:
            s = meta["fn"](velas, symbol, cfg)
            if s:
                s.setdefault("timeframe", timeframe)
                señales.append(s)
        except Exception:
            continue
    return señales
