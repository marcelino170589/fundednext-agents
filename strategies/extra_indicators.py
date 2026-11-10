# strategies/extra_indicators.py
"""
Indicadores adicionales: Bollinger Breakout, RSI Divergence,
MA Crossover y MACD Signal.
"""
from statistics import mean


def _sma(values, period):
    if len(values) < period:
        return []
    return [mean(values[i:i + period]) for i in range(len(values) - period + 1)]


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


def _rsi(values, period=14):
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


# ═══════════════════════════════════════════════════════════════
# 1. BOLLINGER BREAKOUT
# ═══════════════════════════════════════════════════════════════
def bollinger_breakout(velas, symbol, cfg, period=20, std_mult=2.0):
    if len(velas) < period + 5:
        return None

    closes = [v["close"] for v in velas]
    window = closes[-period:]
    mid = mean(window)
    std = (sum((c - mid) ** 2 for c in window) / period) ** 0.5
    upper = mid + std_mult * std
    lower = mid - std_mult * std

    window_prev = closes[-period-1:-1]
    mid_prev = mean(window_prev)
    std_prev = (sum((c - mid_prev) ** 2 for c in window_prev) / period) ** 0.5
    upper_prev = mid_prev + std_mult * std_prev
    lower_prev = mid_prev - std_mult * std_prev

    close = closes[-1]
    close_prev = closes[-2]

    a = _atr(velas, 20)
    if a <= 0:
        return None

    if close > upper and close_prev <= upper_prev:
        direction = "LONG"
        entry = close
        sl = entry - a * 1.5
        risk = entry - sl
        tp = entry + risk * 2.0
    elif close < lower and close_prev >= lower_prev:
        direction = "SHORT"
        entry = close
        sl = entry + a * 1.5
        risk = sl - entry
        tp = entry - risk * 2.0
    else:
        return None

    return {
        "strategy": "bollinger_breakout",
        "timeframe": "D1/H4",
        "direction": direction,
        "entry": round(entry, 5),
        "sl": round(sl, 5),
        "tp": round(tp, 5),
        "confidence": 68,
        "reason": f"Ruptura banda {'superior' if direction == 'LONG' else 'inferior'}",
        "stop_atr": 1.5,
        "trailing_atr": 2.0,
    }


# ═══════════════════════════════════════════════════════════════
# 2. RSI DIVERGENCE
# ═══════════════════════════════════════════════════════════════
def rsi_divergence(velas, symbol, cfg, rsi_period=14, lookback=20):
    if len(velas) < rsi_period + lookback + 5:
        return None

    closes = [v["close"] for v in velas]
    rsi = _rsi(closes, rsi_period)
    if len(rsi) < lookback + 1:
        return None

    ventana_precios = closes[-lookback:]
    ventana_rsi = rsi[-lookback:]

    if len(ventana_precios) < lookback or len(ventana_rsi) < lookback:
        return None

    min_precio_idx = min(range(len(ventana_precios)), key=lambda i: ventana_precios[i])
    max_precio_idx = max(range(len(ventana_precios)), key=lambda i: ventana_precios[i])

    a = _atr(velas, 14)
    if a <= 0:
        return None

    if min_precio_idx >= lookback - 5:
        primeros = ventana_precios[:lookback - 3]
        if primeros:
            min_prev = min(primeros)
            rsi_min_prev = ventana_rsi[primeros.index(min_prev)]
            min_curr = ventana_precios[min_precio_idx]
            rsi_min_curr = ventana_rsi[min_precio_idx]
            if min_curr < min_prev and rsi_min_curr > rsi_min_prev:
                entry = closes[-1]
                sl = min_curr - a * 0.5
                risk = entry - sl
                tp = entry + risk * 2.5
                return {
                    "strategy": "rsi_divergence",
                    "timeframe": "H1/H4",
                    "direction": "LONG",
                    "entry": round(entry, 5),
                    "sl": round(sl, 5),
                    "tp": round(tp, 5),
                    "confidence": 72,
                    "reason": "Divergencia alcista RSI",
                    "stop_atr": 0.5,
                    "trailing_atr": 2.0,
                }

    if max_precio_idx >= lookback - 5:
        primeros = ventana_precios[:lookback - 3]
        if primeros:
            max_prev = max(primeros)
            rsi_max_prev = ventana_rsi[primeros.index(max_prev)]
            max_curr = ventana_precios[max_precio_idx]
            rsi_max_curr = ventana_rsi[max_precio_idx]
            if max_curr > max_prev and rsi_max_curr < rsi_max_prev:
                entry = closes[-1]
                sl = max_curr + a * 0.5
                risk = sl - entry
                tp = entry - risk * 2.5
                return {
                    "strategy": "rsi_divergence",
                    "timeframe": "H1/H4",
                    "direction": "SHORT",
                    "entry": round(entry, 5),
                    "sl": round(sl, 5),
                    "tp": round(tp, 5),
                    "confidence": 72,
                    "reason": "Divergencia bajista RSI",
                    "stop_atr": 0.5,
                    "trailing_atr": 2.0,
                }

    return None


# ═══════════════════════════════════════════════════════════════
# 3. MA CROSSOVER
# ═══════════════════════════════════════════════════════════════
def ma_crossover(velas, symbol, cfg, fast=20, slow=50):
    if len(velas) < slow + 5:
        return None

    closes = [v["close"] for v in velas]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    if len(ema_fast) < 3 or len(ema_slow) < 3:
        return None

    if len(ema_fast) > len(ema_slow):
        fast_al = ema_fast[slow - fast:]
        slow_al = ema_slow
    else:
        fast_al = ema_fast
        slow_al = ema_slow[fast - slow:]

    if len(fast_al) < 3:
        return None

    cruz_alc = fast_al[-2] <= slow_al[-2] and fast_al[-1] > slow_al[-1]
    cruz_baj = fast_al[-2] >= slow_al[-2] and fast_al[-1] < slow_al[-1]

    if not (cruz_alc or cruz_baj):
        return None

    a = _atr(velas, 20)
    if a <= 0:
        return None

    entry = closes[-1]

    if cruz_alc:
        direction = "LONG"
        sl = entry - a * 2
        risk = entry - sl
        tp = entry + risk * 2.0
        razon = "EMA20 cruza sobre EMA50"
    else:
        direction = "SHORT"
        sl = entry + a * 2
        risk = sl - entry
        tp = entry - risk * 2.0
        razon = "EMA20 cruza bajo EMA50"

    return {
        "strategy": "ma_crossover",
        "timeframe": "D1/H4",
        "direction": direction,
        "entry": round(entry, 5),
        "sl": round(sl, 5),
        "tp": round(tp, 5),
        "confidence": 70,
        "reason": razon,
        "stop_atr": 2.0,
        "trailing_atr": 2.5,
    }


# ═══════════════════════════════════════════════════════════════
# 4. MACD SIGNAL
# ═══════════════════════════════════════════════════════════════
def macd_signal(velas, symbol, cfg, fast=12, slow=26, signal=9):
    if len(velas) < slow + signal + 5:
        return None

    closes = [v["close"] for v in velas]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    if len(ema_fast) < len(ema_slow):
        offset = slow - fast
        ema_fast_al = ema_fast[offset:]
        ema_slow_al = ema_slow
    else:
        offset = fast - slow
        ema_fast_al = ema_fast
        ema_slow_al = ema_slow[offset:]

    n = min(len(ema_fast_al), len(ema_slow_al))
    if n < signal + 2:
        return None

    macd_line = [ema_fast_al[i] - ema_slow_al[i] for i in range(n)]
    signal_line = _ema(macd_line, signal)
    if len(signal_line) < 2:
        return None

    macd_prev = macd_line[-len(signal_line):][-2]
    macd_curr = macd_line[-len(signal_line):][-1]
    sig_prev = signal_line[-2]
    sig_curr = signal_line[-1]

    cruz_alc = macd_prev <= sig_prev and macd_curr > sig_curr
    cruz_baj = macd_prev >= sig_prev and macd_curr < sig_curr

    if not (cruz_alc or cruz_baj):
        return None

    a = _atr(velas, 20)
    if a <= 0:
        return None

    entry = closes[-1]

    if cruz_alc and macd_curr > 0:
        direction = "LONG"
        sl = entry - a * 1.5
        risk = entry - sl
        tp = entry + risk * 2.0
        razon = "MACD cruza sobre signal (alcista)"
    elif cruz_baj and macd_curr < 0:
        direction = "SHORT"
        sl = entry + a * 1.5
        risk = sl - entry
        tp = entry - risk * 2.0
        razon = "MACD cruza bajo signal (bajista)"
    else:
        return None

    return {
        "strategy": "macd_signal",
        "timeframe": "H1/H4/D1",
        "direction": direction,
        "entry": round(entry, 5),
        "sl": round(sl, 5),
        "tp": round(tp, 5),
        "confidence": 67,
        "reason": razon,
        "stop_atr": 1.5,
        "trailing_atr": 2.0,
    }
