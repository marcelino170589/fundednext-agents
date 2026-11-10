# strategies/trullas.py
"""
Aproximación pública al "Método Trullás" / MACD triple divergencia.

Fuentes públicas describen a David Trullás Vila como campeón de la World Cup
Trading Championships (futuros) y resumen su operativa en:
  - divergencia del MACD (triple, en las descripciones más recientes),
  - confirmación con RSI y volumen,
  - niveles de Fibonacci / soportes y resistencias,
  - esperar la llegada al nivel, no anticiparse,
  - stop que solo se mueve a favor,
  - primer objetivo y límite de pérdida diario.

Esta implementación NO es el método oficial registrado por el autor ni cuenta
con su validación. Es una traducción técnica conservadora de las reglas
públicas, pensada para el catálogo y el cazador del sistema. No promete los
resultados de competición y debe backtestearse antes de usar en vivo.

Estrategia:
  1. Detectar 3 pivotes de precio con divergencia en MACD (máximos crecientes
     con MACD decreciente, o mínimos decrecientes con MACD creciente).
  2. Confirmar con RSI y volumen.
  3. Exigir que el precio esté en una zona de Fibonacci relevante.
  4. Entrada en el cierre, SL más allá del pivote + colchón ATR,
     TP al primer objetivo (1.5R por defecto).
"""
from __future__ import annotations

from statistics import mean

STRATEGY_ID = "trullas_macd_triple_divergence"
MIN_BARS = 90
PIVOT_LEFT = 2
PIVOT_RIGHT = 2
FIB_LEVELS = (0.236, 0.382, 0.5, 0.618, 0.786)


def _ema_series(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _macd(closes: list[float], fast: int = 12, slow: int = 26,
          signal: int = 9) -> tuple[list[float | None], list[float | None], list[float | None]]:
    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)
    line: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            line[i] = ema_fast[i] - ema_slow[i]
    valid = [v for v in line if v is not None]
    sig_valid = _ema_series(valid, signal)
    sig: list[float | None] = [None] * len(closes)
    first = next((i for i, v in enumerate(line) if v is not None), None)
    if first is not None:
        for offset, value in enumerate(sig_valid):
            if value is not None and first + offset < len(sig):
                sig[first + offset] = value
    hist: list[float | None] = [
        (line[i] - sig[i]) if line[i] is not None and sig[i] is not None else None
        for i in range(len(closes))
    ]
    return line, sig, hist


def _rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def _atr(velas: list[dict], period: int = 14) -> float:
    if len(velas) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(velas)):
        high, low = float(velas[i]["high"]), float(velas[i]["low"])
        prev = float(velas[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev), abs(low - prev)))
    return mean(trs[-period:])


def _pivots(values: list[float], kind: str, left: int = PIVOT_LEFT,
            right: int = PIVOT_RIGHT) -> list[int]:
    pivots: list[int] = []
    for i in range(left, len(values) - right):
        window = values[i - left:i + right + 1]
        center = values[i]
        if kind == "high":
            if center >= max(window) and center > values[i - 1] and center > values[i + 1]:
                pivots.append(i)
        else:
            if center <= min(window) and center < values[i - 1] and center < values[i + 1]:
                pivots.append(i)
    return pivots


def _triple_divergence(prices: list[float], macd_line: list[float | None],
                       rsi: list[float | None], side: str) -> dict | None:
    pivots = _pivots(prices, "high" if side == "bearish" else "low")
    # Necesitamos tres pivotes confirmados y suficientemente separados.
    usable = [i for i in pivots if macd_line[i] is not None and rsi[i] is not None]
    if len(usable) < 3:
        return None
    p = usable[-3:]
    if p[1] - p[0] < 3 or p[2] - p[1] < 3:
        return None

    price_values = [prices[i] for i in p]
    macd_values = [macd_line[i] for i in p]
    rsi_values = [rsi[i] for i in p]

    if side == "bearish":
        price_div = price_values[2] > price_values[1] > price_values[0]
        macd_div = macd_values[2] < macd_values[1] < macd_values[0]
        rsi_div = rsi_values[2] < rsi_values[1]
    else:
        price_div = price_values[2] < price_values[1] < price_values[0]
        macd_div = macd_values[2] > macd_values[1] > macd_values[0]
        rsi_div = rsi_values[2] > rsi_values[1]

    if not (price_div and macd_div):
        return None
    return {
        "pivots": p,
        "price_values": price_values,
        "macd_values": macd_values,
        "rsi_values": rsi_values,
        "rsi_confirmed": bool(rsi_div),
    }


def _fib_zone(velas: list[dict], side: str, atr_value: float,
              lookback: int = 90) -> dict | None:
    window = velas[-lookback:]
    highs = [float(v["high"]) for v in window]
    lows = [float(v["low"]) for v in window]
    high, low = max(highs), min(lows)
    span = high - low
    if span <= 0 or atr_value <= 0:
        return None
    close = float(velas[-1]["close"])
    tolerance = max(atr_value * 0.45, span * 0.015)
    if side == "bearish":
        levels = {f"fib_{int(f * 1000)}": high - span * f for f in FIB_LEVELS}
    else:
        levels = {f"fib_{int(f * 1000)}": low + span * f for f in FIB_LEVELS}
    nearest_name, nearest_price = min(levels.items(), key=lambda item: abs(close - item[1]))
    distance = abs(close - nearest_price)
    return {
        "near": distance <= tolerance,
        "level": round(nearest_price, 6),
        "name": nearest_name,
        "distance": round(distance, 6),
        "tolerance": round(tolerance, 6),
        "range_high": round(high, 6),
        "range_low": round(low, 6),
    }


def trullas_macd_triple_divergence(velas: list[dict], symbol: str, cfg) -> dict | None:
    """Detector conservador. Devuelve una señal compatible con el catálogo."""
    try:
        if not isinstance(velas, list) or len(velas) < MIN_BARS:
            return None
        closes = [float(v["close"]) for v in velas]
        if any(c <= 0 for c in closes):
            return None

        macd_line, macd_signal, macd_hist = _macd(closes)
        rsi = _rsi_series(closes, 14)
        atr_value = _atr(velas, 14)
        if atr_value <= 0 or macd_line[-1] is None or macd_signal[-1] is None:
            return None

        direction = None
        if macd_hist[-1] is not None and macd_hist[-1] < 0:
            direction = "bearish"
        elif macd_hist[-1] is not None and macd_hist[-1] > 0:
            direction = "bullish"
        if direction is None:
            return None

        div = _triple_divergence(
            [float(v["high"]) for v in velas] if direction == "bearish"
            else [float(v["low"]) for v in velas],
            macd_line, rsi, direction,
        )
        if not div:
            return None

        # La entrada debe estar en una zona de Fibonacci, no en cualquier sitio.
        zone = _fib_zone(velas, direction, atr_value)
        if not zone or not zone["near"]:
            return None

        volumes = [float(v.get("volume") or 0) for v in velas[-21:-1]]
        avg_volume = mean(volumes) if volumes else 0.0
        current_volume = float(velas[-1].get("volume") or 0)
        volume_confirmed = bool(avg_volume > 0 and current_volume >= avg_volume * 1.15)

        rsi_value = rsi[-1]
        rsi_confirmed = div["rsi_confirmed"]
        if direction == "bearish" and rsi_value is not None and rsi_value > 72:
            rsi_confirmed = True
        if direction == "bullish" and rsi_value is not None and rsi_value < 28:
            rsi_confirmed = True

        entry = closes[-1]
        last_pivot = div["pivots"][-1]
        if direction == "bearish":
            stop_anchor = max(float(velas[last_pivot]["high"]), float(velas[-1]["high"]))
            sl = stop_anchor + atr_value * 0.35
            risk = max(sl - entry, atr_value * 0.25)
            tp = entry - risk * 1.5
            trade_direction = "SHORT"
        else:
            stop_anchor = min(float(velas[last_pivot]["low"]), float(velas[-1]["low"]))
            sl = stop_anchor - atr_value * 0.35
            risk = max(entry - sl, atr_value * 0.25)
            tp = entry + risk * 1.5
            trade_direction = "LONG"

        if risk <= 0:
            return None

        confidence = 52
        components = {
            "macd_triple_divergence": True,
            "rsi_confirmation": bool(rsi_confirmed),
            "volume_confirmation": volume_confirmed,
            "fibonacci_level": True,
            "level_name": zone["name"],
            "level_price": zone["level"],
            "pivots": div["pivots"],
            "rsi_value": round(rsi_value, 2) if rsi_value is not None else None,
            "volume_ratio": round(current_volume / avg_volume, 2) if avg_volume else None,
        }
        if rsi_confirmed:
            confidence += 9
        if volume_confirmed:
            confidence += 7
        if direction == "bearish" and rsi_value is not None and rsi_value > 65:
            confidence += 4
        if direction == "bullish" and rsi_value is not None and rsi_value < 35:
            confidence += 4
        if zone["near"]:
            confidence += 5
        confidence = min(88, confidence)

        reason = (
            f"MACD triple divergencia {direction} + "
            f"{'RSI ' if rsi_confirmed else ''}"
            f"{'volumen ' if volume_confirmed else ''}"
            f"zona {zone['name']} ({zone['level']})"
        )
        return {
            "strategy": STRATEGY_ID,
            "direction": trade_direction,
            "entry": round(entry, 6),
            "sl": round(sl, 6),
            "tp": round(tp, 6),
            "confidence": confidence,
            "reason": reason,
            "components": components,
            "stop_atr": 2.0,
            "trailing_atr": 2.0,
            "rr": 1.5,
            "source": "public_summary",
        }
    except Exception:
        # Una vela mal formada no debe romper el escaneo de 60 instrumentos.
        return None
