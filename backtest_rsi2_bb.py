# backtest_rsi2_bb.py
"""
Backtest de Bollinger Bands + RSI para XAUUSD.
Basado en la estrategia que pasó el test de robustez en oro M15.
Reglas:
  - LONG: cierre < banda inferior (20,2) Y RSI(14) < 30
  - SHORT: cierre > banda superior (20,2) Y RSI(14) > 70
  - Stop: 1 ATR(14)
  - Salida: precio toca banda media (SMA 20)
"""
import argparse
import csv
from dataclasses import dataclass
from statistics import mean, stdev


@dataclass
class Trade:
    entry_time: str
    direction: str
    entry: float
    stop: float
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


def sma(values, period):
    return [mean(values[i:i+period]) for i in range(len(values)-period+1)]


def rsi(values, period=14):
    if len(values) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag, al = mean(gains[:period]), mean(losses[:period])
    res = []
    for i in range(period, len(gains)+1):
        if i > period:
            ag = (ag*(period-1) + gains[i-1]) / period
            al = (al*(period-1) + losses[i-1]) / period
        res.append(100.0 if al == 0 else 100 - 100/(1+ag/al))
    return res


def atr(velas, period=14):
    if len(velas) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["high"], velas[i]["low"], velas[i-1]["close"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return mean(trs[-period:])


def run_rsi2_bb(symbol, velas, bb_period=20, bb_std=2.0, rsi_period=14,
                rsi_oversold=30, rsi_overbought=70):
    closes = [v["close"] for v in velas]
    if len(closes) < bb_period + rsi_period + 10:
        return {"error": "datos insuficientes"}

    sma_vals = sma(closes, bb_period)
    rsi_vals = rsi(closes, rsi_period)
    if len(sma_vals) < 2 or len(rsi_vals) < 2:
        return {"error": "indicadores insuficientes"}

    # Alinear índices
    offset_sma = len(closes) - len(sma_vals)
    offset_rsi = len(closes) - len(rsi_vals)

    trades = []
    in_pos = False
    pos_dir = None
    pos_entry = 0.0
    pos_stop = 0.0
    pos_entry_idx = 0

    start = max(offset_sma, offset_rsi) + 2
    for i in range(start, len(closes) - 1):
        sma_idx = i - offset_sma
        rsi_idx = i - offset_rsi
        if sma_idx < 1 or rsi_idx < 1:
            continue

        # Bollinger bands
        window = closes[i - bb_period + 1:i + 1]
        if len(window) < bb_period:
            continue
        mid = mean(window)
        std = stdev(window) if len(window) > 1 else 0
        upper = mid + bb_std * std
        lower = mid - bb_std * std
        close = closes[i]

        # Gestión de posición abierta
        if in_pos:
            v = velas[i]
            if pos_dir == "LONG":
                if v["low"] <= pos_stop:
                    risk = abs(pos_entry - pos_stop)
                    r = (pos_stop - pos_entry) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop, pos_stop,
                                        "win" if r > 0 else "loss",
                                        round(r, 2), i - pos_entry_idx))
                    in_pos = False
                    continue
                if v["high"] >= mid:
                    risk = abs(pos_entry - pos_stop)
                    r = (mid - pos_entry) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop, mid,
                                        "win" if r > 0 else "loss",
                                        round(r, 2), i - pos_entry_idx))
                    in_pos = False
                    continue
            else:
                if v["high"] >= pos_stop:
                    risk = abs(pos_stop - pos_entry)
                    r = (pos_entry - pos_stop) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop, pos_stop,
                                        "win" if r > 0 else "loss",
                                        round(r, 2), i - pos_entry_idx))
                    in_pos = False
                    continue
                if v["low"] <= mid:
                    risk = abs(pos_stop - pos_entry)
                    r = (pos_entry - mid) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop, mid,
                                        "win" if r > 0 else "loss",
                                        round(r, 2), i - pos_entry_idx))
                    in_pos = False
                    continue
            continue

        # Nueva entrada
        rsi_val = rsi_vals[rsi_idx]
        if close < lower and rsi_val < rsi_oversold:
            # LONG
            entry_idx = i + 1
            if entry_idx >= len(velas):
                break
            entry = velas[entry_idx]["open"]
            a = atr(velas[max(0, i-14):i+1], 14)
            if a <= 0:
                continue
            pos_dir = "LONG"
            pos_entry = entry
            pos_stop = entry - a * 1.0
            pos_entry_idx = entry_idx
            in_pos = True
        elif close > upper and rsi_val > rsi_overbought:
            # SHORT
            entry_idx = i + 1
            if entry_idx >= len(velas):
                break
            entry = velas[entry_idx]["open"]
            a = atr(velas[max(0, i-14):i+1], 14)
            if a <= 0:
                continue
            pos_dir = "SHORT"
            pos_entry = entry
            pos_stop = entry + a * 1.0
            pos_entry_idx = entry_idx
            in_pos = True

    # Cerrar al final
    if in_pos:
        last = velas[-1]["close"]
        risk = abs(pos_entry - pos_stop)
        r = ((last - pos_entry) / risk if pos_dir == "LONG"
             else (pos_entry - last) / risk) if risk > 0 else 0
        trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir, pos_entry,
                            pos_stop, last, "win" if r > 0 else "loss",
                            round(r, 2), len(velas) - 1 - pos_entry_idx))

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
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--d1", required=True)
    ap.add_argument("--bb-period", type=int, default=20)
    ap.add_argument("--bb-std", type=float, default=2.0)
    ap.add_argument("--rsi-period", type=int, default=14)
    ap.add_argument("--rsi-oversold", type=int, default=30)
    ap.add_argument("--rsi-overbought", type=int, default=70)
    a = ap.parse_args()

    velas = load_csv(a.d1)
    print(f"[data] {a.symbol}: {len(velas)} velas D1")
    r = run_rsi2_bb(a.symbol, velas, a.bb_period, a.bb_std,
                    a.rsi_period, a.rsi_oversold, a.rsi_overbought)
    print("\n═══ RESULTADOS RSI2+BB ═══")
    for k, v in r.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
