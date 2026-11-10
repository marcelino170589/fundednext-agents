# context_builder.py
"""
Construye contexto enriquecido para cada agente.
Incluye:
- Contexto fundamental (noticias)
- Contexto técnico (OHLC + estructura HTF)
- Contexto de mercado (correlaciones)
- Contexto de rentabilidad (FNL:004)
"""
from datetime import datetime
from calendar_client import ventana_bloqueada, get_eventos_hoy
from mt5_ohlc_client import OHLCSubscriber
from config import ZMQ_PC_IP

_ohlc = OHLCSubscriber(host=ZMQ_PC_IP)


# ═══════════════════════════════════════════════════════════════
# Contexto fundamental (agente B)
# ═══════════════════════════════════════════════════════════════

def build_fundamental_context(symbol: str) -> str:
    bloqueado, motivo = ventana_bloqueada(symbol)
    eventos = get_eventos_hoy()
    lineas = [f"Fecha UTC: {datetime.utcnow().isoformat()}"]
    lineas.append("Modo FNL: noticias permitidas, pero solo 40% de ganancias cuentan.")
    if bloqueado:
        lineas.append(f"ALERTA: {motivo}. Considerar bloquear.")
    for ev in eventos[:10]:
        lineas.append(
            f"- {ev.get('Date')} | {ev.get('Currency')} | "
            f"{ev.get('Event')} | Imp: {ev.get('Importance')} | "
            f"Act: {ev.get('Actual')} | Fcst: {ev.get('Forecast')}"
        )
    return "\n".join(lineas)


# ═══════════════════════════════════════════════════════════════
# Contexto HTF (para el agente técnico)
# ═══════════════════════════════════════════════════════════════

def build_htf_context(symbol: str) -> str:
    """Contexto de estructura HTF para el agente técnico."""
    import json
    import os

    htf_file = "data/htf_state.json"
    if not os.path.exists(htf_file):
        return "Sin análisis HTF disponible."

    try:
        with open(htf_file) as f:
            data = json.load(f)
        m = data.get("symbols", {}).get(symbol)
        if not m:
            return f"Sin análisis HTF activo para {symbol}."

        h1 = m.get("h1", {})
        h4 = m.get("h4", {})

        lineas = [f"ESTRUCTURA HTF para {symbol}:"]
        lineas.append(f"  H1: dirección={h1.get('trend_direction')}, "
                     f"estado={h1.get('state')}")
        lineas.append(f"  H4: dirección={h4.get('trend_direction')}, "
                     f"estado={h4.get('state')}")

        pb = h1.get("pullback") or {}
        if pb:
            lineas.append(f"  Retroceso H1: {pb.get('retracement_pct')}% "
                         f"({pb.get('pips')} pips)")
            lineas.append(f"  En zona clave: {pb.get('near_key_zone')}")
            lineas.append(f"  Vela rechazo: {pb.get('rejection_candle')}")

        zonas = h1.get("key_zones", [])
        if zonas:
            lineas.append("  Zonas clave cercanas:")
            for z in zonas[:2]:
                lineas.append(f"    - {z['type']}: {z['price']} "
                             f"({z['distance_pct']:.1f}%)")

        return "\n".join(lineas)
    except Exception as e:
        return f"Error cargando HTF: {e}"


# ═══════════════════════════════════════════════════════════════
# Contexto técnico (agente C) — incluye HTF
# ═══════════════════════════════════════════════════════════════

def build_technical_context(symbol: str) -> str:
    data = _ohlc.get_full(symbol)
    if not data:
        return "OHLC no disponible (MT5 sin conexión)."

    h1 = data.get("h1", {})
    h4 = data.get("h4", {})

    base = (
        f"{symbol}:\n"
        f"H1 O={h1.get('open', '—')} H={h1.get('high', '—')} "
        f"L={h1.get('low', '—')} C={h1.get('close', '—')}\n"
        f"Velas H1: {len(data.get('h1_velas', []))} | "
        f"H4: {len(data.get('h4_velas', []))}\n"
    )

    # Última vela H1
    h1_velas = data.get("h1_velas", [])
    if h1_velas:
        last = h1_velas[-1]
        base += (
            f"Última vela H1: {last.get('time')} | "
            f"O={last.get('open')} H={last.get('high')} "
            f"L={last.get('low')} C={last.get('close')}\n"
        )

    # Última vela H4
    h4_velas = data.get("h4_velas", [])
    if h4_velas:
        last4 = h4_velas[-1]
        base += (
            f"Última vela H4: {last4.get('time')} | "
            f"O={last4.get('open')} H={last4.get('high')} "
            f"L={last4.get('low')} C={last4.get('close')}\n"
        )

    base += "\n" + build_htf_context(symbol)
    return base


# ═══════════════════════════════════════════════════════════════
# Contexto de mercado (agente A)
# ═══════════════════════════════════════════════════════════════

def build_market_context(symbol: str) -> str:
    base = symbol[:3] if symbol[:3] != "XAU" else "XAU"
    quote = symbol[3:] if len(symbol) > 3 else "USD"
    return (
        f"Símbolo {symbol}. Base: {base}, Cotizada: {quote}. "
        f"Cuenta FNL: 50K, trailing DD $2,000, consistency 20%. "
        f"Usa el OHLC de H1 como referencia de estructura. "
        f"Considera correlaciones típicas (oro vs USD, etc.)."
    )


# ═══════════════════════════════════════════════════════════════
# Contexto de rentabilidad (todos los agentes)
# ═══════════════════════════════════════════════════════════════

def build_profit_context(snap: dict) -> str:
    """Contexto adaptado a FNL:004 (20% consistency)."""
    if not snap:
        return "Sin datos de rentabilidad."

    dilution = snap.get("dilution", {})
    objetivo = snap.get("objetivo_diario_efectivo", 100)
    presupuesto = snap.get("presupuesto_restante_hoy", 0)
    ratio = snap.get("ratio_consistencia", 0)
    falta = snap.get("falta_para_20pct", 0)

    if dilution.get("active"):
        modo = (f"⚠ MODO DILUCIÓN ACTIVO\n"
                f"  Ratio: {ratio:.1f}% (límite 20%)\n"
                f"  Objetivo diario reducido: ${objetivo:.0f}\n"
                f"  Falta diluir: ${falta:.0f}\n"
                f"  NO propongas trades > ${presupuesto:.0f}")
    elif ratio > 15:
        modo = (f"⚠ CERCA DEL LÍMITE DE CONSISTENCIA\n"
                f"  Ratio: {ratio:.1f}% (límite 20%)\n"
                f"  Falta: ${falta:.0f}\n"
                f"  Prioriza trades PEQUEÑOS")
    else:
        modo = f"Modo normal. Objetivo diario: ${objetivo:.0f}"

    return (
        f"ESTADO FNL:004 (cuenta {snap.get('account_id', '?')}):\n"
        f"  P&L hoy: ${snap.get('daily_pnl', 0):.2f}\n"
        f"  P&L ciclo: ${snap.get('total_pnl_ciclo', 0):.2f}\n"
        f"  Mejor día (perpetuo): ${snap.get('best_day_pnl', 0):.2f}\n"
        f"  Ratio consistency: {ratio:.1f}% (límite 20%)\n"
        f"  Peak equity: ${snap.get('peak_equity', 0):.2f}\n"
        f"  Trailing floor: ${snap.get('trailing_floor', 0):.2f}\n"
        f"  Presupuesto hoy: ${presupuesto:.2f}\n\n"
        f"{modo}\n"
    )
