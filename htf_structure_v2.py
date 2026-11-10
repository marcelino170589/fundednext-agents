# htf_structure_v2.py
"""Detector de estructura H1/H4 multi-activo."""
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict
from symbol_config import SymbolConfig, get_config


@dataclass
class Impulse:
    direction: str; start_idx: int; end_idx: int
    start_price: float; end_price: float
    pips: float; ratio_atr: float; candles: int
    start_time: str; end_time: str


@dataclass
class Pullback:
    pips: float; retracement_pct: float; candles_elapsed: int
    at_ema20: bool; at_ema50: bool
    at_fib_level: Optional[str]
    near_key_zone: bool; rejection_candle: bool


@dataclass
class KeyZone:
    type: str; price: float
    distance_pips: float; distance_pct: float


def _ema(values, period):
    if len(values) < period: return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _atr(velas, period=14):
    if len(velas) < period + 1: return 0.0
    trs = []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["high"], velas[i]["low"], velas[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


def detectar_impulso(velas, cfg: SymbolConfig) -> Optional[Impulse]:
    if len(velas) < 20: return None
    atr = _atr(velas, cfg.atr_period)
    if atr <= 0: return None
    min_rango = atr * cfg.min_atr_impulse
    for end in range(len(velas) - 1, 20, -1):
        for direction in ("LONG", "SHORT"):
            count = 0
            for i in range(end, 20, -1):
                v = velas[i]
                es_alc = v["close"] > v["open"]
                if (direction == "LONG" and es_alc) or (direction == "SHORT" and not es_alc):
                    count += 1
                else:
                    break
                if count >= cfg.impulse_min_candles:
                    start = i
                    sp, ep = velas[start]["open"], velas[end]["close"]
                    rango = abs(ep - sp)
                    if rango >= min_rango:
                        return Impulse(direction, start, end, sp, ep,
                                        round(rango / cfg.pip_size, 1),
                                        round(rango / atr, 2), count,
                                        velas[start]["time"], velas[end]["time"])
                    break
    return None


def calcular_retroceso(velas, impulso, cfg) -> Optional[Pullback]:
    post = velas[impulso.end_idx + 1:]
    if not post: return None
    cierres = [v["close"] for v in velas]
    ema20 = _ema(cierres, 20)
    ema50 = _ema(cierres, 50)
    if impulso.direction == "LONG":
        ext, actual = max(v["high"] for v in post), post[-1]["close"]
        retro = ext - actual
    else:
        ext, actual = min(v["low"] for v in post), post[-1]["close"]
        retro = actual - ext
    if retro <= 0: return None
    rango = abs(impulso.end_price - impulso.start_price)
    pct = min(100, retro / rango * 100)
    if pct < cfg.min_pullback_pct: return None
    sign = 1 if impulso.direction == "LONG" else -1
    fibs = {"38.2": impulso.end_price - rango * 0.382 * sign,
            "50":   impulso.end_price - rango * 0.50 * sign,
            "61.8": impulso.end_price - rango * 0.618 * sign}
    tol = rango * (cfg.key_zone_tolerance_pct / 100.0)
    at_fib = next((k for k, v in fibs.items() if abs(actual - v) <= tol), None)
    ema20v = ema20[-1] if ema20 else None
    ema50v = ema50[-1] if ema50 else None
    etol = rango * 0.03
    at_20 = bool(ema20v and abs(actual - ema20v) <= etol)
    at_50 = bool(ema50v and abs(actual - ema50v) <= etol)
    last = post[-1]
    body = abs(last["close"] - last["open"])
    mecha = (last["high"] - max(last["open"], last["close"])) if impulso.direction == "LONG" \
            else (min(last["open"], last["close"]) - last["low"])
    rejection = mecha > body * 1.5
    return Pullback(round(retro / cfg.pip_size, 1), round(pct, 1), len(post),
                    at_20, at_50, at_fib, (at_fib is not None or at_20 or at_50), rejection)


def zonas_clave(velas, impulso, cfg, actual):
    rango = abs(impulso.end_price - impulso.start_price)
    sign = 1 if impulso.direction == "LONG" else -1
    zonas = []
    for name, pct in [("38.2", 0.382), ("50", 0.50), ("61.8", 0.618)]:
        lvl = impulso.end_price - rango * pct * sign
        zonas.append(KeyZone(f"fib_{name.replace('.', '_')}", round(lvl, 5),
                              round(abs(actual - lvl) / cfg.pip_size, 1),
                              round(abs(actual - lvl) / rango * 100, 2)))
    cierres = [v["close"] for v in velas]
    for p in (20, 50):
        e = _ema(cierres, p)
        if e:
            zonas.append(KeyZone(f"ema{p}", round(e[-1], 5),
                                  round(abs(actual - e[-1]) / cfg.pip_size, 1),
                                  round(abs(actual - e[-1]) / rango * 100, 2)))
    rec = velas[-20:]
    piv = min(v["low"] for v in rec) if impulso.direction == "LONG" \
          else max(v["high"] for v in rec)
    zonas.append(KeyZone("pivot", round(piv, 5),
                          round(abs(actual - piv) / cfg.pip_size, 1),
                          round(abs(actual - piv) / rango * 100, 2)))
    return sorted(zonas, key=lambda z: z.distance_pct)


def clasificar_estado(imp, pb, zonas, cfg):
    if not pb: return "IMPULSE"
    pct = pb.retracement_pct
    if pct > cfg.max_pullback_pct: return "REVERSAL_SIGNAL"
    if pb.near_key_zone and pb.rejection_candle and pct >= 38: return "PULLBACK_ENDING"
    if pb.near_key_zone: return "PULLBACK_AT_KEY_ZONE"
    if pct >= 30: return "PULLBACK_IN_PROGRESS"
    if pct >= cfg.min_pullback_pct: return "PULLBACK_STARTING"
    return "IMPULSE"


def analizar(symbol, velas_h1, velas_h4):
    cfg = get_config(symbol)
    if not cfg or len(velas_h1) < 60 or len(velas_h4) < 60: return None
    try:
        hora = datetime.fromisoformat(velas_h1[-1]["time"]).hour
    except (ValueError, KeyError):
        hora = datetime.utcnow().hour
    if symbol.upper().startswith("XAU") and not (7 <= hora < 20):
        return None
    resultados = {}
    for tf, velas in [("H1", velas_h1), ("H4", velas_h4)]:
        imp = detectar_impulso(velas, cfg)
        if not imp:
            resultados[tf] = {"trend_direction": None, "state": "NO_IMPULSE"}
            continue
        pb = calcular_retroceso(velas, imp, cfg)
        zonas = zonas_clave(velas, imp, cfg, velas[-1]["close"])
        resultados[tf] = {"trend_direction": imp.direction,
                          "state": clasificar_estado(imp, pb, zonas, cfg),
                          "impulse": asdict(imp),
                          "pullback": asdict(pb) if pb else None,
                          "key_zones": [asdict(z) for z in zonas[:3]]}
    h1, h4 = resultados["H1"], resultados["H4"]
    alineados = bool(h4.get("trend_direction") and h1.get("trend_direction")
                     and h4["trend_direction"] == h1["trend_direction"])
    return {"symbol": symbol, "h1": h1, "h4": h4,
            "timeframes_aligned": alineados,
            "detected_at": datetime.utcnow().isoformat()}