# backtest_wyckoff.py
"""
Backtest de Wyckoff simplificado (versión relajada).
Detecta acumulación → spring → ruptura (markup).
Condiciones más permisivas para generar trades en XAUUSD.
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
    target: float
    exit_price: float
    result: str
    r_multiple: float
    duration: int
    fase: str


def load_csv(path):
    with open(path) as f:
        return [{"time": r["time"], "open": float(r["open"]),
                 "high": float(r["high"]), "low": float(r["low"]),
                 "close": float(r["close"]),
                 "volume": float(r.get("volume", 0))}
                for r in csv.DictReader(f)]


def detectar_rango(velas, i, lookback=10, max_rango_pct=10.0):
    """Detecta rango lateral con condiciones relajadas."""
    if i < lookback + 5:
        return None
    
    ventana = velas[i - lookback:i]
    highs = [v["high"] for v in ventana]
    lows = [v["low"] for v in ventana]
    max_h = max(highs)
    min_l = min(lows)
    
    if min_l <= 0:
        return None
    
    altura_pct = (max_h - min_l) / min_l * 100
    if altura_pct > max_rango_pct:
        return None
    
    return max_h, min_l, max_h - min_l


def detectar_spring(velas, i, min_l, max_h, lookback=10):
    """Detecta spring con mecha inferior >= 40%."""
    if i < lookback:
        return None
    
    for j in range(i - lookback, i):
        v = velas[j]
        rango_v = v["high"] - v["low"]
        if rango_v <= 0:
            continue
        
        mecha_inf = min(v["open"], v["close"]) - v["low"]
        if mecha_inf / rango_v < 0.4:  # Relajado: 60% → 40%
            continue
        
        if v["low"] < min_l and v["close"] > min_l:
            return j
    
    return None


def run_wyckoff(symbol, velas, rr=2.0, max_duration=30):
    if len(velas) < 50:
        return {"error": "datos insuficientes"}
    
    trades = []
    in_pos = False
    pos_dir = None
    pos_entry = 0.0
    pos_stop = 0.0
    pos_target = 0.0
    pos_entry_idx = 0
    
    spring_activo = None
    
    for i in range(20, len(velas) - 1):
        v = velas[i]
        
        # Gestión de posición abierta
        if in_pos:
            if pos_dir == "LONG":
                if v["low"] <= pos_stop:
                    risk = abs(pos_entry - pos_stop)
                    r = (pos_stop - pos_entry) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop, pos_target, pos_stop,
                                        "win" if r > 0 else "loss", round(r, 2),
                                        i - pos_entry_idx, "markup"))
                    in_pos = False
                    continue
                if v["high"] >= pos_target:
                    risk = abs(pos_entry - pos_stop)
                    r = (pos_target - pos_entry) / risk if risk > 0 else 0
                    trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                        pos_entry, pos_stop, pos_target, pos_target,
                                        "win", round(r, 2), i - pos_entry_idx, "markup"))
                    in_pos = False
                    continue
            
            if i - pos_entry_idx >= max_duration:
                exit_p = v["close"]
                risk = abs(pos_entry - pos_stop)
                r = (exit_p - pos_entry) / risk if risk > 0 else 0
                trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir,
                                    pos_entry, pos_stop, pos_target, exit_p,
                                    "win" if r > 0 else "loss", round(r, 2),
                                    i - pos_entry_idx, "timeout"))
                in_pos = False
            continue
        
        # Detectar rango (relajado)
        rango = detectar_rango(velas, i, lookback=10, max_rango_pct=10.0)
        if not rango:
            continue
        
        max_h, min_l, altura = rango
        
        # Detectar spring (relajado)
        spring_idx = detectar_spring(velas, i, min_l, max_h, lookback=10)
        if spring_idx is None:
            continue
        
        spring_activo = (spring_idx, min_l, max_h, altura)
        
        # Ruptura del máximo del rango
        if v["close"] > max_h and spring_activo and (i - spring_activo[0]) <= 30:
            spring_idx, spring_min, rango_max, rango_altura = spring_activo
            
            entry_idx = i + 1
            if entry_idx >= len(velas):
                break
            entry = velas[entry_idx]["open"]
            stop = spring_min * 0.999
            target = entry + rango_altura * rr
            
            pos_dir = "LONG"
            pos_entry = entry
            pos_stop = stop
            pos_target = target
            pos_entry_idx = entry_idx
            in_pos = True
            spring_activo = None
    
    if in_pos:
        last = velas[-1]["close"]
        risk = abs(pos_entry - pos_stop)
        r = (last - pos_entry) / risk if risk > 0 else 0
        trades.append(Trade(velas[pos_entry_idx]["time"], pos_dir, pos_entry,
                            pos_stop, pos_target, last,
                            "win" if r > 0 else "loss", round(r, 2),
                            len(velas) - 1 - pos_entry_idx, "timeout"))
    
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
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--max-duration", type=int, default=30)
    a = ap.parse_args()
    
    velas = load_csv(a.d1)
    print(f"[data] {a.symbol}: {len(velas)} velas")
    r = run_wyckoff(a.symbol, velas, a.rr, a.max_duration)
    print("\n═══ RESULTADOS WYCKOFF ═══")
    for k, v in r.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
