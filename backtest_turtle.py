# backtest_turtle.py
"""
Backtest del sistema Turtle Trading (Richard Dennis).
Reglas clásicas:
  - Sistema 1: ruptura de máximo/mínimo de 20 velas.
    - Si la última señal fue ganadora, se salta la siguiente.
    - Salida: ruptura de mínimo/máximo de 10 velas.
  - Sistema 2: ruptura de máximo/mínimo de 55 velas.
    - Siempre se opera (no se salta señales).
    - Salida: ruptura de mínimo/máximo de 20 velas.
  - Stop: 2 × ATR(20).
  - Tamaño de posición: riesgo fijo (1% del capital por trade).

Uso:
    python backtest_turtle.py --symbol XAUUSD --d1 data/XAUUSD_D1.csv --sistema 1
    python backtest_turtle.py --symbol XAUUSD --d1 data/XAUUSD_D1.csv --sistema 2
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


def run_turtle(symbol, velas, sistema=1, stop_atr=2.0):
    """
    sistema: 1 (20/10) o 2 (55/20).
    stop_atr: múltiplo de ATR para el stop.
    """
    if sistema == 1:
        entry_period = 20
        exit_period = 10
    else:
        entry_period = 55
        exit_period = 20

    if len(velas) < entry_period + 10:
        return {"error": "datos insuficientes"}

    trades = []
    in_pos = False
    pos_dir = None
    pos_entry = 0.0
    pos_stop = 0.0
    pos_entry_idx = 0
    last_signal_won = False

    start = entry_period + 1
    for i in range(start, len(velas) - 1):
        # Calcular máximo/mínimo de entry_period velas anteriores
        highs = [v["high"] for v in velas[i - entry_period:i]]
        lows = [v["low"] for v in velas[i - entry_period:i]]
        max_h = max(highs)
        min_l = min(lows)
        close = velas[i]["close"]

        # ═══ GESTIÓN DE POSICIÓN ABIERTA ═══
        if in_pos:
            vela = velas[i]

            # Verificar stop
            if pos_dir == "LONG":
                if vela["low"] <= pos_stop:
                    risk = abs(pos_entry - pos_stop)
                    r = (pos_stop - pos_entry) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop, pos_stop,
                                        "win" if r > 0 else "loss",
                                        round(r, 2), i - pos_entry_idx))
                    last_signal_won = r > 0
                    in_pos = False
                    continue
            else:
                if vela["high"] >= pos_stop:
                    risk = abs(pos_stop - pos_entry)
                    r = (pos_entry - pos_stop) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop, pos_stop,
                                        "win" if r > 0 else "loss",
                                        round(r, 2), i - pos_entry_idx))
                    last_signal_won = r > 0
                    in_pos = False
                    continue

            # Verificar salida por ruptura de exit_period
            exit_highs = [v["high"] for v in velas[i - exit_period:i]]
            exit_lows = [v["low"] for v in velas[i - exit_period:i]]
            exit_max = max(exit_highs)
            exit_min = min(exit_lows)

            if pos_dir == "LONG" and close < exit_min:
                exit_price = close
                risk = abs(pos_entry - pos_stop)
                r = (exit_price - pos_entry) / risk if risk > 0 else 0
                trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                    pos_entry, pos_stop, exit_price,
                                    "win" if r > 0 else "loss",
                                    round(r, 2), i - pos_entry_idx))
                last_signal_won = r > 0
                in_pos = False
                continue
            elif pos_dir == "SHORT" and close > exit_max:
                exit_price = close
                risk = abs(pos_stop - pos_entry)
                r = (pos_entry - exit_price) / risk if risk > 0 else 0
                trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                    pos_entry, pos_stop, exit_price,
                                    "win" if r > 0 else "loss",
                                    round(r, 2), i - pos_entry_idx))
                last_signal_won = r > 0
                in_pos = False
                continue

            continue

        # ═══ NUEVA ENTRADA ═══
        # Sistema 1: saltar señal si la última ganó
        if sistema == 1 and last_signal_won:
            last_signal_won = False
            continue

        # Verificar ruptura
        if close > max_h:
            # LONG
            entry_price = velas[i + 1]["open"]
            atr_val = atr(velas[max(0, i - 20):i + 1], 20)
            if atr_val <= 0:
                continue
            pos_dir = "LONG"
            pos_entry = entry_price
            pos_stop = entry_price - atr_val * stop_atr
            pos_entry_idx = i + 1
            in_pos = True
        elif close < min_l:
            # SHORT
            entry_price = velas[i + 1]["open"]
            atr_val = atr(velas[max(0, i - 20):i + 1], 20)
            if atr_val <= 0:
                continue
            pos_dir = "SHORT"
            pos_entry = entry_price
            pos_stop = entry_price + atr_val * stop_atr
            pos_entry_idx = i + 1
            in_pos = True

    # Cerrar al final si queda abierta
    if in_pos:
        last = velas[-1]["close"]
        risk = abs(pos_entry - pos_stop)
        r = ((last - pos_entry) / risk if pos_dir == "LONG"
             else (pos_entry - last) / risk) if risk > 0 else 0
        trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                            pos_entry, pos_stop, last,
                            "win" if r > 0 else "loss",
                            round(r, 2), len(velas) - 1 - pos_entry_idx))

    # Métricas
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
        "sistema": sistema,
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
    ap.add_argument("--sistema", type=int, default=1, choices=[1, 2])
    ap.add_argument("--stop-atr", type=float, default=2.0)
    a = ap.parse_args()

    velas = load_csv(a.d1)
    print(f"[data] {a.symbol}: {len(velas)} velas D1")
    r = run_turtle(a.symbol, velas, a.sistema, a.stop_atr)
    print("\n═══ RESULTADOS TURTLE ═══")
    for k, v in r.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
