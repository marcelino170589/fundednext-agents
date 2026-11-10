# simular_en_vivo.py
"""
Simula el sistema completo con datos históricos (para fin de semana).
Carga los últimos N días de velas de cada par y ejecuta el cazador.
"""
import csv
from pathlib import Path
from datetime import datetime, timedelta

from agents import agent_opportunity_hunter
from config import INITIAL_BALANCE

DATA_DIR = Path("data")
PAIRS = ["XAUUSD", "USDJPY", "EURUSD", "USDCAD"]


def load_ultimos(p, dias=90):
    """Carga las últimas N velas de un CSV."""
    if not Path(p).exists():
        return []
    with open(p) as f:
        velas = [{"time": r["time"], "open": float(r["open"]),
                  "high": float(r["high"]), "low": float(r["low"]),
                  "close": float(r["close"]),
                  "volume": float(r.get("volume", 0))}
                 for r in csv.DictReader(f)]
    # Devolver las últimas N velas
    return velas[-dias:] if len(velas) > dias else velas


def simular_sistema_vivo():
    print("═" * 70)
    print("  SIMULACIÓN DEL SISTEMA EN VIVO (con datos históricos)")
    print(f"  Fecha: {datetime.utcnow().isoformat()} UTC")
    print("═" * 70)
    print()

    velas_por_symbol = {}
    for symbol in PAIRS:
        # Cargar suficientes velas para D1 (60+), H4 (60+), H1 (60+)
        d1 = load_ultimos(DATA_DIR / f"{symbol}_D1.csv", dias=120)
        h4 = load_ultimos(DATA_DIR / f"{symbol}_H4.csv", dias=200)
        h1 = load_ultimos(DATA_DIR / f"{symbol}_H1.csv", dias=300)

        if d1:
            velas_por_symbol[symbol] = {"D1": d1, "H4": h4, "H1": h1}
            print(f"  {symbol}: D1={len(d1)}, H4={len(h4)}, H1={len(h1)}")
        else:
            print(f"  {symbol}: ⚠️ sin datos")

    print()
    print("─── Ejecutando cazador ───")
    print()

    # Ejecutar cazador con confluencia ≥2
    oportunidades = agent_opportunity_hunter.run(
        velas_por_symbol=velas_por_symbol,
        balance=INITIAL_BALANCE,
        top_n=5,
        usar_fundamental=True,
        min_confluencia=2,
    )

    if not oportunidades:
        print("🎯 No hay oportunidades con confluencia ≥2")
        print("   (normal: el sistema es ultra-selectivo)")
        print()

        # Probar con confluencia ≥1 para ver si hay alguna señal
        print("─── Probando con confluencia ≥1 ───")
        oportunidades = agent_opportunity_hunter.run(
            velas_por_symbol=velas_por_symbol,
            balance=INITIAL_BALANCE,
            top_n=5,
            usar_fundamental=False,
            min_confluencia=1,
        )
        if oportunidades:
            print(f"🎯 {len(oportunidades)} oportunidad(es) con confluencia ≥1:")
        else:
            print("🎯 Tampoco hay oportunidades con confluencia ≥1")
            print("   (las estrategias no generan señal con los datos actuales)")
            return

    print(f"🎯 {len(oportunidades)} oportunidad(es):")
    print()
    for i, op in enumerate(oportunidades, 1):
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
        print(f"     Score:   {op['score']}")
        print(f"     Macro:   {macro.get('veredicto')} ({macro.get('confianza')}%)")
        print()


if __name__ == "__main__":
    simular_sistema_vivo()
