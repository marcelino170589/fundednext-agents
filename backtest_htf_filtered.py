# backtest_htf_filtered.py
"""
Backtest del módulo HTF con filtros adicionales:
1. Solo PULLBACK_ENDING (rechazo confirmado)
2. Tendencia H4 alineada con H1
3. Sesión Londres/NY (7-20 UTC)
"""
import argparse
import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from symbol_config import get_config
from htf_structure_v2 import analizar, _atr


@dataclass
class Trade:
    entry_time: str
    direction: str
    state: str
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


def simulate(fut, d, entry, stop, target, max_c=20):
    risk = abs(entry - stop)
    if risk <= 0:
        return "timeout", entry, 0, 0
    for i, v in enumerate(fut[:max_c]):
        if d == "LONG":
            if v["low"] <= stop:
                return "loss", stop, i + 1, -1.0
            if v["high"] >= target:
                return "win", target, i + 1, (target - entry) / risk
        else:
            if v["high"] >= stop:
                return "loss", stop, i + 1, -1.0
            if v["low"] <= target:
                return "win", target, i + 1, (entry - target) / risk
    exit_p = fut[-1]["close"] if fut else entry
    r = (exit_p - entry) / risk if d == "LONG" else (entry - exit_p) / risk
    return "timeout", exit_p, max_c, r


def en_sesion(tiempo_str: str) -> bool:
    """Verifica si la hora está en sesión Londres/NY (7-20 UTC)."""
    try:
        dt = datetime.strptime(tiempo_str[:19], "%Y-%m-%d %H:%M:%S")
        return 7 <= dt.hour < 20
    except (ValueError, IndexError):
        return True  # Si no se puede parsear, permitir


def run_bt_filtered(symbol, h1, h4, rr=2.0, stop_atr=0.5, max_c=20, start=100,
                    filtro_estado=True, filtro_h4=True, filtro_sesion=True):
    cfg = get_config(symbol)
    if not cfg:
        return {"error": "no config"}
    trades = []
    in_pos = False
    rechazos = {"estado": 0, "h4": 0, "sesion": 0}

    for i in range(start, len(h1) - max_c):
        if in_pos:
            in_pos = False
            continue
        h1_s = h1[max(0, i - 100):i + 1]
        curr = h1[i]["time"]
        h4_s = [v for v in h4 if v["time"] <= curr][-100:]
        if len(h4_s) < 60:
            continue
        est = analizar(symbol, h1_s, h4_s)
        if not est:
            continue

        state = est["h1"].get("state")
        d = est["h1"].get("trend_direction")
        if not d:
            continue

        # FILTRO 1: Solo PULLBACK_ENDING
        if filtro_estado:
            if state != "PULLBACK_ENDING":
                rechazos["estado"] += 1
                continue
        else:
            if state not in ("PULLBACK_AT_KEY_ZONE", "PULLBACK_ENDING"):
                continue

        # FILTRO 2: Tendencia H4 alineada
        if filtro_h4:
            h4_dir = est["h4"].get("trend_direction")
            if h4_dir != d:
                rechazos["h4"] += 1
                continue

        # FILTRO 3: Sesión Londres/NY
        if filtro_sesion:
            if not en_sesion(curr):
                rechazos["sesion"] += 1
                continue

        entry = h1[i]["close"]
        atr_v = _atr(h1_s, cfg.atr_period)
        buf = atr_v * stop_atr
        if d == "LONG":
            stop = min(v["low"] for v in h1_s[-5:]) - buf
            risk = entry - stop
            target = entry + risk * rr
        else:
            stop = max(v["high"] for v in h1_s[-5:]) + buf
            risk = stop - entry
            target = entry - risk * rr
        if risk <= 0:
            continue

        fut = h1[i + 1:i + 1 + max_c]
        res, exit_p, dur, r = simulate(fut, d, entry, stop, target, max_c)
        trades.append(Trade(h1[i]["time"], d, state, entry, stop,
                            target, exit_p, res, r, dur))
        in_pos = True

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
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "hit_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "profit_factor": round(gw / gl, 2) if gl > 0 else 0,
        "avg_r": round(sum(t.r_multiple for t in trades) / len(trades), 2) if trades else 0,
        "total_r": round(eq, 2),
        "max_dd_r": round(dd, 2),
        "rechazos": rechazos,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--h1", required=True)
    ap.add_argument("--h4", required=True)
    ap.add_argument("--rr", type=float, default=1.5)
    ap.add_argument("--output")
    ap.add_argument("--sin-filtro-estado", action="store_true")
    ap.add_argument("--sin-filtro-h4", action="store_true")
    ap.add_argument("--sin-filtro-sesion", action="store_true")
    a = ap.parse_args()

    h1 = load_csv(a.h1)
    h4 = load_csv(a.h4)
    print(f"[data] {a.symbol}: {len(h1)} H1, {len(h4)} H4")

    m = run_bt_filtered(
        a.symbol, h1, h4, rr=a.rr,
        filtro_estado=not a.sin_filtro_estado,
        filtro_h4=not a.sin_filtro_h4,
        filtro_sesion=not a.sin_filtro_sesion,
    )

    print("\n═══ RESULTADOS (con filtros) ═══")
    for k in ("trades", "wins", "losses", "hit_rate", "profit_factor",
              "avg_r", "total_r", "max_dd_r"):
        print(f"  {k}: {m.get(k)}")
    print(f"  rechazos: {m.get('rechazos')}")

    if a.output:
        with open(a.output, "w") as f:
            json.dump(m, f, indent=2, default=str)
        print(f"\n✓ Guardado en {a.output}")


if __name__ == "__main__":
    main()
