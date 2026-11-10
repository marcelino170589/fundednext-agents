# backtest_htf.py
"""
Backtest del módulo HTF con grid search y walk-forward.
Uso:
    python backtest_htf.py --symbol XAUUSD --h1 data/XAUUSD_H1.csv --h4 data/XAUUSD_H4.csv
    python backtest_htf.py --symbol XAUUSD --h1 ... --h4 ... --grid-search
    python backtest_htf.py --symbol XAUUSD --h1 ... --h4 ... --walk-forward
"""
import argparse
import csv
import json
from dataclasses import dataclass, asdict
from itertools import product
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


def run_bt(symbol, h1, h4, rr=2.0, stop_atr=0.5, max_c=20, start=100):
    cfg = get_config(symbol)
    if not cfg:
        return {"error": "no config"}
    trades = []
    in_pos = False

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
        if state not in ("PULLBACK_AT_KEY_ZONE", "PULLBACK_ENDING"):
            continue
        d = est["h1"].get("trend_direction")
        if not d:
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

    return {"trades": len(trades), "wins": len(wins), "losses": len(losses),
            "hit_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "profit_factor": round(gw / gl, 2) if gl > 0 else 0,
            "avg_r": round(sum(t.r_multiple for t in trades) / len(trades), 2) if trades else 0,
            "total_r": round(eq, 2), "max_dd_r": round(dd, 2)}


def grid_search(symbol, h1, h4, out=None):
    """Grid search de parámetros."""
    import symbol_config
    cfg = get_config(symbol)
    if not cfg:
        return {"error": "no config"}
    
    grid = {
        "min_atr_impulse": [1.5, 2.0, 2.5, 3.0],
        "min_pullback_pct": [10, 15, 20, 25],
        "key_zone_tolerance_pct": [3, 5, 7],
        "rr": [1.5, 2.0, 2.5],
    }
    keys = list(grid.keys())
    total = 1
    for v in grid.values():
        total *= len(v)
    print(f"[grid] {total} combinaciones a probar")
    
    results = []
    for idx, combo in enumerate(product(*grid.values())):
        params = dict(zip(keys, combo))
        rr = params.pop("rr")
        
        test_cfg = symbol_config.DEFAULT_CONFIGS[symbol].__class__(
            name=cfg.name, pip_size=cfg.pip_size,
            pip_value_per_lot=cfg.pip_value_per_lot,
            min_atr_impulse=params["min_atr_impulse"],
            min_pullback_pct=params["min_pullback_pct"],
            max_pullback_pct=cfg.max_pullback_pct,
            key_zone_tolerance_pct=params["key_zone_tolerance_pct"],
            volatility_window=cfg.volatility_window,
            atr_period=cfg.atr_period,
            impulse_min_candles=cfg.impulse_min_candles,
        )
        orig = symbol_config.DEFAULT_CONFIGS[symbol]
        symbol_config.DEFAULT_CONFIGS[symbol] = test_cfg
        try:
            m = run_bt(symbol, h1, h4, rr=rr)
            m["params"] = params
            m["rr"] = rr
            results.append(m)
        finally:
            symbol_config.DEFAULT_CONFIGS[symbol] = orig
        if (idx + 1) % 20 == 0:
            print(f"  {idx + 1}/{total}")
    
    valid = [r for r in results if r.get("trades", 0) >= 20]
    if not valid:
        return {"error": "sin resultados válidos"}
    
    top = {
        "best_pf": max(valid, key=lambda x: x.get("profit_factor", 0)),
        "best_hit": max(valid, key=lambda x: x.get("hit_rate", 0)),
        "best_avg_r": max(valid, key=lambda x: x.get("avg_r", 0)),
    }
    
    if out:
        with open(out, "w") as f:
            json.dump({"top": top, "all": results}, f, indent=2, default=str)
        print(f"[grid] resultados guardados en {out}")
    
    return top


def walk_forward(symbol, h1, h4, n_windows=4, train_pct=0.7):
    """Walk-forward validation."""
    results = []
    window_size = len(h1) // n_windows
    
    for w in range(n_windows):
        start = w * window_size
        end = start + window_size
        if end > len(h1):
            break
        
        h1_win = h1[start:end]
        h4_win = [v for v in h4 if h1_win[0]["time"] <= v["time"] <= h1_win[-1]["time"]]
        
        train_h1 = h1_win[:int(len(h1_win) * train_pct)]
        test_h1 = h1_win[int(len(h1_win) * train_pct):]
        train_h4 = [v for v in h4_win if v["time"] <= train_h1[-1]["time"]]
        test_h4 = [v for v in h4_win if v["time"] >= test_h1[0]["time"]]
        
        if len(test_h1) < 100 or len(test_h4) < 60:
            continue
        
        print(f"\n[wf] Ventana {w + 1}/{n_windows}")
        train_top = grid_search(symbol, train_h1, train_h4)
        
        if "error" in train_top:
            continue
        
        best_params = train_top["best_pf"]["params"]
        best_rr = train_top["best_pf"]["rr"]
        
        import symbol_config
        cfg = symbol_config.DEFAULT_CONFIGS[symbol]
        test_cfg = symbol_config.DEFAULT_CONFIGS[symbol].__class__(
            name=cfg.name, pip_size=cfg.pip_size,
            pip_value_per_lot=cfg.pip_value_per_lot,
            min_atr_impulse=best_params["min_atr_impulse"],
            min_pullback_pct=best_params["min_pullback_pct"],
            max_pullback_pct=cfg.max_pullback_pct,
            key_zone_tolerance_pct=best_params["key_zone_tolerance_pct"],
            volatility_window=cfg.volatility_window,
            atr_period=cfg.atr_period,
            impulse_min_candles=cfg.impulse_min_candles,
        )
        symbol_config.DEFAULT_CONFIGS[symbol] = test_cfg
        try:
            test_metrics = run_bt(symbol, test_h1, test_h4, rr=best_rr)
        finally:
            symbol_config.DEFAULT_CONFIGS[symbol] = cfg
        
        results.append({
            "window": w + 1,
            "train_best": train_top["best_pf"],
            "test_metrics": test_metrics,
        })
        
        print(f"[wf] Train PF={train_top['best_pf']['profit_factor']}, "
              f"Test PF={test_metrics.get('profit_factor', 0)}, "
              f"Test hit={test_metrics.get('hit_rate', 0)}%")
    
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--h1", required=True)
    ap.add_argument("--h4", required=True)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--output")
    ap.add_argument("--grid-search", action="store_true")
    ap.add_argument("--walk-forward", action="store_true")
    a = ap.parse_args()
    
    h1 = load_csv(a.h1)
    h4 = load_csv(a.h4)
    print(f"[data] {a.symbol}: {len(h1)} H1, {len(h4)} H4")
    
    if a.walk_forward:
        results = walk_forward(a.symbol, h1, h4)
        if a.output:
            with open(a.output, "w") as f:
                json.dump(results, f, indent=2, default=str)
        return
    
    if a.grid_search:
        top = grid_search(a.symbol, h1, h4, a.output)
        print("\n════════ MEJORES PARÁMETROS ════════")
        for k in ("best_pf", "best_hit", "best_avg_r"):
            m = top.get(k, {})
            print(f"\n{k}:")
            print(f"  params: {m.get('params')}")
            print(f"  rr: {m.get('rr')}")
            print(f"  trades: {m.get('trades')}")
            print(f"  hit_rate: {m.get('hit_rate')}%")
            print(f"  profit_factor: {m.get('profit_factor')}")
            print(f"  avg_r: {m.get('avg_r')}")
        return
    
    m = run_bt(a.symbol, h1, h4, rr=a.rr)
    print("\n═══ RESULTADOS ═══")
    for k, v in m.items():
        print(f"  {k}: {v}")
    if a.output:
        with open(a.output, "w") as f:
            json.dump(m, f, indent=2)


if __name__ == "__main__":
    main()
