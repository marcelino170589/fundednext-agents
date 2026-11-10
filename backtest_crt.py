# backtest_crt.py
"""
Backtest de CRT (Candle Range Theory) — Patrón de reversión de 3 velas.
Reglas:
  - Vela 1 (Rango): define máximo y mínimo.
  - Vela 2 (Barrido): su mecha rompe un lado de la Vela 1 pero el cuerpo
    cierra de vuelta dentro del rango.
  - Vela 3 (Entrada): se entra cuando el precio rompe el máximo/mínimo
    de la Vela 2 en dirección opuesta al barrido.
  - Stop: en la mecha de la Vela 2.
  - Target: en el extremo opuesto de la Vela 1 (R:R variable).
"""
import argparse
import csv
from dataclasses import dataclass


@dataclass
class Trade:
    entry_time: str
    direction: str
    entry: float
    stop: float
    target: float
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


def detectar_crt(velas, i):
    """
    Detecta patrón CRT en las velas i-2 (rango), i-1 (barrido), i (entrada).
    Devuelve (direction, entry, stop, target) o None.
    """
    if i < 3:
        return None

    v1 = velas[i - 2]  # Vela de rango
    v2 = velas[i - 1]  # Vela de barrido
    v3 = velas[i]      # Vela actual (potencial entrada)

    # Rango de V1
    rango_high = v1["high"]
    rango_low = v1["low"]

    # ¿V2 barrió el high de V1?
    barrido_high = v2["high"] > rango_high and v2["close"] < rango_high
    # ¿V2 barrió el low de V1?
    barrido_low = v2["low"] < rango_low and v2["close"] > rango_low

    if barrido_high:
        # Barrido alcista → señal SHORT
        # Entrada: ruptura del low de V2
        entry = v2["low"]
        stop = v2["high"]
        target = rango_low  # extremo opuesto de V1
        if v3["low"] <= entry:
            return ("SHORT", entry, stop, target)
    elif barrido_low:
        # Barrido bajista → señal LONG
        entry = v2["high"]
        stop = v2["low"]
        target = rango_high
        if v3["high"] >= entry:
            return ("LONG", entry, stop, target)

    return None


def run_crt(symbol, velas, max_duration=20):
    trades = []
    in_pos = False
    pos = None
    pos_entry_idx = 0

    for i in range(3, len(velas) - 1):
        # Gestión de posición abierta
        if in_pos:
            v = velas[i]
            # Verificar stop
            if pos["dir"] == "LONG":
                if v["low"] <= pos["stop"]:
                    risk = pos["entry"] - pos["stop"]
                    r = (pos["stop"] - pos["entry"]) / risk if risk > 0 else 0
                    trades.append(Trade(pos["time"], pos["dir"], pos["entry"],
                                        pos["stop"], pos["target"], pos["stop"],
                                        "win" if r > 0 else "loss", round(r, 2),
                                        i - pos_entry_idx))
                    in_pos = False
                    continue
                if v["high"] >= pos["target"]:
                    risk = pos["entry"] - pos["stop"]
                    r = (pos["target"] - pos["entry"]) / risk if risk > 0 else 0
                    trades.append(Trade(pos["time"], pos["dir"], pos["entry"],
                                        pos["stop"], pos["target"], pos["target"],
                                        "win", round(r, 2), i - pos_entry_idx))
                    in_pos = False
                    continue
            else:
                if v["high"] >= pos["stop"]:
                    risk = pos["stop"] - pos["entry"]
                    r = (pos["entry"] - pos["stop"]) / risk if risk > 0 else 0
                    trades.append(Trade(pos["time"], pos["dir"], pos["entry"],
                                        pos["stop"], pos["target"], pos["stop"],
                                        "win" if r > 0 else "loss", round(r, 2),
                                        i - pos_entry_idx))
                    in_pos = False
                    continue
                if v["low"] <= pos["target"]:
                    risk = pos["stop"] - pos["entry"]
                    r = (pos["entry"] - pos["target"]) / risk if risk > 0 else 0
                    trades.append(Trade(pos["time"], pos["dir"], pos["entry"],
                                        pos["stop"], pos["target"], pos["target"],
                                        "win", round(r, 2), i - pos_entry_idx))
                    in_pos = False
                    continue

            # Timeout
            if i - pos_entry_idx >= max_duration:
                exit_p = v["close"]
                risk = abs(pos["entry"] - pos["stop"])
                r = ((exit_p - pos["entry"]) / risk if pos["dir"] == "LONG"
                     else (pos["entry"] - exit_p) / risk) if risk > 0 else 0
                trades.append(Trade(pos["time"], pos["dir"], pos["entry"],
                                    pos["stop"], pos["target"], exit_p,
                                    "win" if r > 0 else "loss", round(r, 2),
                                    i - pos_entry_idx))
                in_pos = False
            continue

        # Detectar nuevo patrón
        señal = detectar_crt(velas, i)
        if señal:
            direction, entry, stop, target = señal
            pos = {"dir": direction, "entry": entry, "stop": stop,
                   "target": target, "time": velas[i]["time"]}
            pos_entry_idx = i
            in_pos = True

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
    r = run_crt(a.symbol, velas)
    print("\n═══ RESULTADOS CRT ═══")
    for k, v in r.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
