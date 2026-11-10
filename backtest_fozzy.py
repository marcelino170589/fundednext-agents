# backtest_fozzy.py
"""
Backtest del Método Fozzy (Sergey Malaga) — Versión completa con parámetros ajustables.

Reglas:
  - RSI(8) cruza EMA(8) en D1.
  - Entrada en apertura de vela siguiente.
  - SL inicial: configurable (default 1.5× ATR(20)).
  - Trailing stop: configurable (default 2.0× ATR(20)), solo se mueve a favor.
  - Salida: trailing stop o cruce opuesto (opcional, default off).
  - R se calcula contra el stop inicial.

Uso:
    python backtest_fozzy.py --symbol EURUSD --d1 data/EURUSD_D1.csv
    python backtest_fozzy.py --symbol EURUSD --d1 data/EURUSD_D1.csv --stop-atr 2.0 --trailing-atr 3.0
    python backtest_fozzy.py --symbol EURUSD --d1 data/EURUSD_D1.csv --filtro-ma10
    python backtest_fozzy.py --symbol EURUSD --d1 data/EURUSD_D1.csv --exit-on-cross
"""
import argparse
import csv
from dataclasses import dataclass
from statistics import mean


@dataclass
class Trade:
    entry_time: str
    direction: str
    entry: float
    stop_inicial: float
    stop_final: float
    exit_price: float
    result: str
    r_multiple: float
    duration: int


def load_csv(path):
    with open(path) as f:
        return [{"time": r["time"], "open": float(r["open"]),
                 "high": float(r["high"]), "low": float(r["low"]),
                 "close": float(r["close"])}
                for r in csv.DictReader(f)]


def ema(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


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


def sma(values, period):
    if len(values) < period:
        return []
    return [mean(values[i:i + period]) for i in range(len(values) - period + 1)]


def run_fozzy_backtest(symbol, velas, usar_filtro_ma10=False,
                        stop_atr=1.5, trailing_atr=2.0,
                        exit_on_cross=False):
    """
    velas: lista de velas D1.
    stop_atr: múltiplo de ATR para el stop inicial.
    trailing_atr: múltiplo de ATR para el trailing stop.
    exit_on_cross: si True, cierra en cruce opuesto además del trailing.
    """
    closes = [v["close"] for v in velas]
    if len(closes) < 100:
        return {"error": "datos insuficientes"}

    rsi_vals = rsi(closes, 8)
    rsi_ema = ema(rsi_vals, 8)
    if len(rsi_ema) < 3:
        return {"error": "RSI/EMA insuficientes"}

    offset = len(rsi_vals) - len(rsi_ema)
    rsi_al = rsi_vals[offset:]

    ma10w = sma(closes, 50) if usar_filtro_ma10 else []

    trades = []
    in_pos = False
    pos_dir = None
    pos_entry = 0.0
    pos_stop_ini = 0.0
    pos_stop_act = 0.0
    pos_entry_idx = 0

    start = 60
    for i in range(start, len(rsi_al) - 1):
        close_idx = offset + i
        if close_idx >= len(velas) - 1:
            break

        rsi_prev, rsi_curr = rsi_al[i - 1], rsi_al[i]
        ema_prev, ema_curr = rsi_ema[i - 1], rsi_ema[i]

        cruz_alc = rsi_prev <= ema_prev and rsi_curr > ema_curr
        cruz_baj = rsi_prev >= ema_prev and rsi_curr < ema_curr

        # ═══ GESTIÓN DE POSICIÓN ABIERTA ═══
        if in_pos:
            vela = velas[close_idx]

            # 1. Verificar stop actual
            if pos_dir == "LONG":
                if vela["low"] <= pos_stop_act:
                    exit_price = pos_stop_act
                    risk = abs(pos_entry - pos_stop_ini)
                    r = (exit_price - pos_entry) / risk if risk > 0 else 0
                    trades.append(Trade(
                        velas[pos_entry_idx]["time"], pos_dir, pos_entry,
                        pos_stop_ini, pos_stop_act, exit_price,
                        "win" if r > 0 else "loss", round(r, 2),
                        close_idx - pos_entry_idx,
                    ))
                    in_pos = False
                    continue
            else:
                if vela["high"] >= pos_stop_act:
                    exit_price = pos_stop_act
                    risk = abs(pos_stop_ini - pos_entry)
                    r = (pos_entry - exit_price) / risk if risk > 0 else 0
                    trades.append(Trade(
                        velas[pos_entry_idx]["time"], pos_dir, pos_entry,
                        pos_stop_ini, pos_stop_act, exit_price,
                        "win" if r > 0 else "loss", round(r, 2),
                        close_idx - pos_entry_idx,
                    ))
                    in_pos = False
                    continue

            # 2. Salida por cruce opuesto (opcional)
            if exit_on_cross:
                if (pos_dir == "LONG" and cruz_baj) or (pos_dir == "SHORT" and cruz_alc):
                    exit_price = vela["close"]
                    risk = abs(pos_entry - pos_stop_ini)
                    if pos_dir == "LONG":
                        r = (exit_price - pos_entry) / risk if risk > 0 else 0
                    else:
                        r = (pos_entry - exit_price) / risk if risk > 0 else 0
                    trades.append(Trade(
                        velas[pos_entry_idx]["time"], pos_dir, pos_entry,
                        pos_stop_ini, pos_stop_act, exit_price,
                        "win" if r > 0 else "loss", round(r, 2),
                        close_idx - pos_entry_idx,
                    ))
                    in_pos = False
                    continue

            # 3. Actualizar trailing stop (solo a favor)
            atr_actual = atr(velas[max(0, close_idx - 20):close_idx + 1], 20)
            if pos_dir == "LONG":
                nuevo_stop = vela["close"] - atr_actual * trailing_atr
                if nuevo_stop > pos_stop_act:
                    pos_stop_act = nuevo_stop
            else:
                nuevo_stop = vela["close"] + atr_actual * trailing_atr
                if nuevo_stop < pos_stop_act:
                    pos_stop_act = nuevo_stop
            continue

        # ═══ NUEVA ENTRADA ═══
        if not (cruz_alc or cruz_baj):
            continue

        # Filtro MA10 semanas
        if usar_filtro_ma10 and ma10w:
            ma_idx = close_idx - 49
            if 0 <= ma_idx < len(ma10w):
                ma_val = ma10w[ma_idx]
                if cruz_alc and closes[close_idx] < ma_val:
                    continue
                if cruz_baj and closes[close_idx] > ma_val:
                    continue

        entry_idx = close_idx + 1
        if entry_idx >= len(velas):
            break
        entry_price = velas[entry_idx]["open"]
        atr_val = atr(velas[max(0, close_idx - 20):close_idx + 1], 20)
        if atr_val <= 0:
            continue

        if cruz_alc:
            pos_dir = "LONG"
            pos_stop_ini = entry_price - atr_val * stop_atr
        else:
            pos_dir = "SHORT"
            pos_stop_ini = entry_price + atr_val * stop_atr

        pos_entry = entry_price
        pos_stop_act = pos_stop_ini
        pos_entry_idx = entry_idx
        in_pos = True

    # Cerrar al final si queda abierta
    if in_pos:
        last = velas[-1]["close"]
        risk = abs(pos_entry - pos_stop_ini)
        r = ((last - pos_entry) / risk if pos_dir == "LONG"
             else (pos_entry - last) / risk) if risk > 0 else 0
        trades.append(Trade(
            velas[pos_entry_idx]["time"], pos_dir, pos_entry,
            pos_stop_ini, pos_stop_act, last,
            "win" if r > 0 else "loss", round(r, 2),
            len(velas) - 1 - pos_entry_idx,
        ))

    # ═══ MÉTRICAS ═══
    wins = [t for t in trades if t.result == "win"]
    losses = [t for t in trades if t.result == "loss"]
    gw = sum(t.r_multiple for t in wins)
    gl = abs(sum(t.r_multiple for t in losses))
    eq = peak = dd = 0
    for t in trades:
        eq += t.r_multiple
        peak = max(peak, eq)
        dd = max(dd, peak - eq)

    return {
        "symbol": symbol,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "hit_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "profit_factor": round(gw / gl, 2) if gl > 0 else 0,
        "avg_r": round(sum(t.r_multiple for t in trades) / len(trades), 2) if trades else 0,
        "total_r": round(eq, 2),
        "max_dd_r": round(dd, 2),
        "params": {"stop_atr": stop_atr, "trailing_atr": trailing_atr,
                   "exit_on_cross": exit_on_cross, "filtro_ma10": usar_filtro_ma10},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--d1", required=True)
    ap.add_argument("--filtro-ma10", action="store_true")
    ap.add_argument("--stop-atr", type=float, default=1.5)
    ap.add_argument("--trailing-atr", type=float, default=2.0)
    ap.add_argument("--exit-on-cross", action="store_true")
    a = ap.parse_args()

    velas = load_csv(a.d1)
    print(f"[data] {a.symbol}: {len(velas)} velas D1")
    r = run_fozzy_backtest(a.symbol, velas, a.filtro_ma10,
                            a.stop_atr, a.trailing_atr, a.exit_on_cross)
    print("\n═══ RESULTADOS FOZZY ═══")
    for k, v in r.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
