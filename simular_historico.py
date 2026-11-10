# simular_historico.py
"""
Simula el cazador en una fecha histórica específica.
Carga D1, H4, H1, M15, M5 de todos los CSVs disponibles en data/.
"""
import csv
import sys
from pathlib import Path
from datetime import datetime

from agents import agent_opportunity_hunter
from config import INITIAL_BALANCE, MIN_CONFLUENCIA, SCORE_MINIMO, FILTRAR_CORRELACION

DATA_DIR = Path("data")


def load_hasta(p, fecha):
    """Carga velas hasta una fecha (incluyendo todo el día)."""
    if not Path(p).exists():
        return []
    with open(p) as f:
        velas = [{"time": r["time"], "open": float(r["open"]),
                  "high": float(r["high"]), "low": float(r["low"]),
                  "close": float(r["close"]),
                  "volume": float(r.get("volume", 0))}
                 for r in csv.DictReader(f)]
    fecha_fin = f"{fecha} 23:59:59"
    return [v for v in velas if v["time"] <= fecha_fin]


def get_pairs_disponibles():
    """Detecta todos los pares con al menos un CSV D1."""
    pairs = []
    for f in DATA_DIR.glob("*_D1.csv"):
        symbol = f.stem.replace("_D1", "")
        pairs.append(symbol)
    return sorted(set(pairs))


def simular_en_fecha(fecha_corte, usar_fundamental=False, min_confluencia=None,
                     score_minimo=None, filtrar_correlacion=None):
    """Simula el cazador en una fecha histórica."""
    if min_confluencia is None:
        min_confluencia = MIN_CONFLUENCIA
    if score_minimo is None:
        score_minimo = SCORE_MINIMO
    if filtrar_correlacion is None:
        filtrar_correlacion = FILTRAR_CORRELACION

    pairs = get_pairs_disponibles()

    print(f"═══ SIMULACIÓN EN FECHA: {fecha_corte} ═══")
    print(f"    (incluyendo velas hasta {fecha_corte} 23:59:59)")
    print(f"    Confluencia mínima: {min_confluencia}")
    print(f"    Score mínimo: {score_minimo}")
    print(f"    Filtro correlación: {'SÍ' if filtrar_correlacion else 'NO'}")
    print(f"    Filtro fundamental: {'SÍ' if usar_fundamental else 'NO'}")
    print(f"    Pares disponibles: {len(pairs)}")
    print()

    velas_por_symbol = {}
    for symbol in pairs:
        d1 = load_hasta(DATA_DIR / f"{symbol}_D1.csv", fecha_corte)
        h4 = load_hasta(DATA_DIR / f"{symbol}_H4.csv", fecha_corte)
        h1 = load_hasta(DATA_DIR / f"{symbol}_H1.csv", fecha_corte)
        m15 = load_hasta(DATA_DIR / f"{symbol}_M15.csv", fecha_corte)
        m5 = load_hasta(DATA_DIR / f"{symbol}_M5.csv", fecha_corte)

        if d1:
            velas_por_symbol[symbol] = {
                "D1": d1, "H4": h4, "H1": h1, "M15": m15, "M5": m5,
            }
            print(f"  {symbol}: D1={len(d1)}, H4={len(h4)}, H1={len(h1)}, "
                  f"M15={len(m15)}, M5={len(m5)}")

    print()
    print(f"Ejecutando cazador...")
    print()

    ops = agent_opportunity_hunter.run(
        velas_por_symbol=velas_por_symbol,
        balance=INITIAL_BALANCE,
        top_n=10,
        usar_fundamental=usar_fundamental,
        min_confluencia=min_confluencia,
        score_minimo=score_minimo,
        filtrar_correlacion=filtrar_correlacion,
    )

    if not ops:
        print("🎯 No hay oportunidades en esta fecha.")
        return

    print(f"🎯 {len(ops)} oportunidad(es):")
    print()
    for i, op in enumerate(ops, 1):
        macro = op.get("macro", {})
        emoji = "🟢" if op["direction"] == "LONG" else "🔴"
        print(f"  {emoji} #{i} {op['symbol']} {op['direction']}")
        print(f"     Entrada: {op['entry']}")
        print(f"     SL:      {op['sl']}")
        print(f"     TP:      {op['tp']}")
        print(f"     Lotaje:  {op['lotaje']}")
        print(f"     R:R:     1:{op['rr']}")
        print(f"     Riesgo:  ${op['riesgo_usd']}")
        print(f"     Confluencia: {op['confluencia']} estrategias: {op['estrategias']}")
        print(f"     Timeframes: {op.get('timeframes', [])}")
        print(f"     Score:   {op['score']}")
        print(f"     Macro:   {macro.get('veredicto')} ({macro.get('confianza')}%)")
        print()


if __name__ == "__main__":
    fecha = sys.argv[1] if len(sys.argv) > 1 else "2024-06-15"
    usar_fund = "--fundamental" in sys.argv

    min_conf = MIN_CONFLUENCIA
    if "--min-conf" in sys.argv:
        idx = sys.argv.index("--min-conf")
        if idx + 1 < len(sys.argv):
            min_conf = int(sys.argv[idx + 1])

    score_min = SCORE_MINIMO
    if "--score-min" in sys.argv:
        idx = sys.argv.index("--score-min")
        if idx + 1 < len(sys.argv):
            score_min = int(sys.argv[idx + 1])

    corr = FILTRAR_CORRELACION
    if "--sin-correlacion" in sys.argv:
        corr = False

    simular_en_fecha(fecha, usar_fundamental=usar_fund,
                     min_confluencia=min_conf,
                     score_minimo=score_min,
                     filtrar_correlacion=corr)
