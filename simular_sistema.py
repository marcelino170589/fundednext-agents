# simular_sistema.py
"""
Simulación completa del sistema (paper trading).
- Carga velas históricas de CSVs.
- Ejecuta el cazador de oportunidades con filtro fundamental.
- Muestra el ranking top 3.
- NO envía órdenes reales.
"""
import csv
import json
from pathlib import Path
from datetime import datetime

from agents import agent_opportunity_hunter
from symbol_config import supported_symbols, get_config
from config import INITIAL_BALANCE

DATA_DIR = Path("data")
PAIRS = ["XAUUSD", "USDJPY", "EURUSD", "USDCAD"]


def load_csv(path):
    if not path.exists():
        return []
    with open(path) as f:
        return [{"time": r["time"], "open": float(r["open"]),
                 "high": float(r["high"]), "low": float(r["low"]),
                 "close": float(r["close"]),
                 "volume": float(r.get("volume", 0))}
                for r in csv.DictReader(f)]


def cargar_velas():
    """Carga velas D1, H4 y H1 de cada par."""
    velas_por_symbol = {}
    for symbol in PAIRS:
        d1 = load_csv(DATA_DIR / f"{symbol}_D1.csv")
        h4 = load_csv(DATA_DIR / f"{symbol}_H4.csv")
        h1 = load_csv(DATA_DIR / f"{symbol}_H1.csv")
        if d1:
            velas_por_symbol[symbol] = {"D1": d1, "H4": h4, "H1": h1}
            print(f"  {symbol}: D1={len(d1)}, H4={len(h4)}, H1={len(h1)}")
        else:
            print(f"  {symbol}: ⚠️ sin datos D1")
    return velas_por_symbol


def simular():
    print("═══════════════════════════════════════════════════════")
    print("  SIMULACIÓN DEL SISTEMA PROFESIONAL FNL:004")
    print("  (Paper Trading - Sin órdenes reales)")
    print("═══════════════════════════════════════════════════════")
    print()

    # 1. Cargar velas
    print("─── 1. Cargando velas históricas ───")
    velas_por_symbol = cargar_velas()
    print()

    if not velas_por_symbol:
        print("❌ No hay datos para simular. Descarga CSVs primero.")
        return

    # 2. Ejecutar cazador con filtro fundamental
    print("─── 2. Ejecutando cazador de oportunidades ───")
    print(f"  Balance: ${INITIAL_BALANCE:,.2f}")
    print(f"  Pares: {list(velas_por_symbol.keys())}")
    print(f"  Estrategias: Fozzy, Turtle, Larry, HTF")
    print(f"  Filtro: Macro + Noticias + Confluencia ≥2")
    print()

    try:
        oportunidades = agent_opportunity_hunter.run(
            velas_por_symbol,
            balance=INITIAL_BALANCE,
            top_n=3,
            usar_fundamental=True,
        )
    except Exception as e:
        print(f"❌ Error en el cazador: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. Mostrar resultados
    print("─── 3. Resultados ───")
    print()

    if not oportunidades:
        print("🎯 No se encontraron oportunidades con confluencia ≥2")
        print("   y macro favorable en este momento.")
        print()
        print("   Esto es normal: el sistema es ultra-selectivo.")
        print("   Solo opera cuando hay confluencia real de factores.")
        return

    print(f"🎯 {len(oportunidades)} oportunidad(es) encontrada(s):")
    print()

    for i, op in enumerate(oportunidades, 1):
        macro = op.get("macro", {})
        emoji = "🟢" if op["direction"] == "LONG" else "🔴"

        print(f"  ┌─────────────────────────────────────────────────┐")
        print(f"  │ {emoji} #{i} {op['symbol']} {op['direction']}                          ")
        print(f"  ├─────────────────────────────────────────────────┤")
        print(f"  │ Entrada:    {op['entry']}")
        print(f"  │ Stop Loss:  {op['sl']}")
        print(f"  │ Take Profit:{op['tp']}")
        print(f"  │ Lotaje:     {op['lotaje']}")
        print(f"  │ R:R:        1:{op['rr']}")
        print(f"  │ Riesgo:     ${op['riesgo_usd']}")
        print(f"  │")
        print(f"  │ Macro:      {macro.get('veredicto')} (conf {macro.get('confianza')}%)")
        print(f"  │ Razón:      {macro.get('razon', '')[:60]}")
        print(f"  │ Catalizador:{macro.get('catalizador', '')[:50]}")
        print(f"  │")
        print(f"  │ Confluencia: {op['confluencia']}/5 estrategias")
        print(f"  │ Estrategias: {', '.join(op['estrategias'])}")
        print(f"  │ Score:       {op['score']}")
        print(f"  └─────────────────────────────────────────────────┘")
        print()

    # 4. Generar mensajes de Telegram (sin enviar)
    print("─── 4. Mensajes que recibirías en Telegram ───")
    print()

    for op in oportunidades:
        macro = op.get("macro", {})
        emoji = "🟢" if op["direction"] == "LONG" else "🔴"
        msg = (
            f"{emoji} OPORTUNIDAD: {op['symbol']} {op['direction']}\n\n"
            f"💰 Entrada: {op['entry']}\n"
            f"🛑 SL: {op['sl']}\n"
            f"🎯 TP: {op['tp']}\n"
            f"📦 Lotaje: {op['lotaje']}\n"
            f"⚖️ R:R: 1:{op['rr']}\n\n"
            f"🏛️ Macro: {macro.get('veredicto')} (conf {macro.get('confianza')}%)\n"
            f"📝 {macro.get('razon', '')[:80]}\n\n"
            f"🔥 Confluencia: {op['confluencia']}/5 estrategias\n"
            f"🧠 Estrategias: {', '.join(op['estrategias'])}\n"
            f"📈 Score: {op['score']}\n"
            f"💵 Riesgo: ${op['riesgo_usd']}\n\n"
            f"⚠️ Ejecuta MANUALMENTE en MT5"
        )
        print("─" * 55)
        print(msg)
        print()

    # 5. Resumen
    print("─── 5. Resumen de la simulación ───")
    print(f"  Hora: {datetime.utcnow().isoformat()} UTC")
    print(f"  Pares escaneados: {len(velas_por_symbol)}")
    print(f"  Oportunidades: {len(oportunidades)}")
    print(f"  Mejor score: {oportunidades[0]['score']}")
    print()


if __name__ == "__main__":
    simular()
