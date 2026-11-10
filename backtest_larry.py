# backtest_larry.py
"""
Backtest de Larry Williams:
  - Dirección: media de 10 semanas (50 días en D1).
  - Timing: Williams %R (sobreventa < -80 para LONG, sobrecompra > -20 para SHORT).
  - Entrada: cuando %R sale de sobreventa/sobrecompra en dirección de la MA10.
  - Stop: 2.0 × ATR(20).
  - Trailing: 3.0 × ATR(20).
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


def atr(velas, period=20):
    if len(velas) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["high"], velas[i]["low"], velas[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return mean(trs[-period:])


def williams_r(velas, period=14):
    """Williams %R: -100 a 0."""
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


def run_larry(symbol, velas, stop_atr=2.0, trailing_atr=3.0):
    closes = [v["close"] for v in velas]
    if len(closes) < 100:
        return {"error": "datos insuficientes"}

    wr = williams_r(velas, 14)
    if len(wr) < 3:
        return {"error": "Williams %R insuficientes"}

    trades = []
    in_pos = False
    pos_dir = None
    pos_entry = 0.0
    pos_stop_ini = 0.0
    pos_stop_act = 0.0
    pos_entry_idx = 0

    start = 60
    for i in range(start, len(velas) - 1):
        wr_idx = i - 13  # wr empieza en el índice 13
        if wr_idx < 1 or wr_idx >= len(wr):
            continue
        wr_prev = wr[wr_idx - 1]
        wr_curr = wr[wr_idx]

        ma10w = mean(closes[i - 49:i + 1]) if i >= 49 else None
        if ma10w is None:
            continue

        close = velas[i]["close"]

        # Gestión de posición
        if in_pos:
            v = velas[i]
            if pos_dir == "LONG":
                if v["low"] <= pos_stop_act:
                    risk = abs(pos_entry - pos_stop_ini)
                    r = (pos_stop_act - pos_entry) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop_ini, pos_stop_act,
                                        "win" if r > 0 else "loss", round(r, 2),
                                        i - pos_entry_idx))
                    in_pos = False
                    continue
            else:
                if v["high"] >= pos_stop_act:
                    risk = abs(pos_stop_ini - pos_entry)
                    r = (pos_entry - pos_stop_act) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop_ini, pos_stop_act,
                                        "win" if r > 0 else "loss", round(r, 2),
                                        i - pos_entry_idx))
                    in_pos = False
                    continue

            # Trailing
            a = atr(velas[max(0, i - 20):i + 1], 20)
            if pos_dir == "LONG":
                nuevo = v["close"] - a * trailing_atr
                if nuevo > pos_stop_act:
                    pos_stop_act = nuevo
            else:
                nuevo = v["close"] + a * trailing_atr
                if nuevo < pos_stop_act:
                    pos_stop_act = nuevo
            continue

        # Nueva entrada
        # LONG: precio > MA10 y %R sale de sobreventa (<-80 a >-80)
        if close > ma10w and wr_prev < -80 and wr_curr >= -80:
            entry = velas[i + 1]["open"]
            a = atr(velas[max(0, i - 20):i + 1], 20)
            if a <= 0:
                continue
            pos_dir = "LONG"
            pos_entry = entry
            pos_stop_ini = entry - a * stop_atr
            pos_stop_act = pos_stop_ini
            pos_entry_idx = i + 1
            in_pos = True
        # SHORT: precio < MA10 y %R sale de sobrecompra (>-20 a <-20)
        elif close < ma10w and wr_prev > -20 and wr_curr <= -20:
            entry = velas[i + 1]["open"]
            a = atr(velas[max(0, i - 20):i + 1], 20)
            if a <= 0:
                continue
            pos_dir = "SHORT"
            pos_entry = entry
            pos_stop_ini = entry + a * stop_atr
            pos_stop_act = pos_stop_ini
            pos_entry_idx = i + 1
            in_pos = True

    # Cerrar abierta
    if in_pos:
        last = velas[-1]["close"]
        risk = abs(pos_entry - pos_stop_ini)
        r = ((last - pos_entry) / risk if pos_dir == "LONG"
             else (pos_entry - last) / risk) if risk > 0 else 0
        trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir, pos_entry,
                            pos_stop_ini, last,
                            "win" if r > 0 else "loss", round(r, 2),
                            len(velas) - 1 - pos_entry_idx))

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
    a = ap.parse_args()
    velas = load_csv(a.d1)
    print(f"[data] {a.symbol}: {len(velas)} velas D1")
    r = run_larry(a.symbol, velas)
    print("\n═══ RESULTADOS LARRY WILLIAMS ═══")
    for k, v in r.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
