# agents/agent_opportunity_hunter.py
"""
Agente Cazador de Oportunidades con filtro fundamental, caché,
correlación y score mínimo configurable.

Escanea todos los instrumentos (forex, índices, commodities, metales).
Integra 10 estrategias + HTF + MTF.
"""
import logging
import time
from statistics import mean
from strategies.catalog import (
    fozzy, turtle, larry, order_flow, rsi2_bb,
)
from strategies.extra_indicators import (
    bollinger_breakout, rsi_divergence, ma_crossover, macd_signal,
)
from strategies.trullas import trullas_macd_triple_divergence
from symbol_config import get_config, supported_symbols
from calendar_client import ventana_bloqueada

log = logging.getLogger("hunter")

# Caché de veredicto macro (1 hora)
_macro_cache = {}
_MACRO_TTL = 3600

# Grupos de correlación (pares que se mueven juntos)
CORRELATION_GROUPS = {
    "USD_BLOC": {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"},
    "JPY_BLOC": {"USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY"},
    "COMMODITY_BLOC": {"AUDUSD", "NZDUSD", "USDCAD", "XAUUSD", "XAGUSD", "XPTUSD", "UKOUSD", "USOUSD"},
    "EURO_BLOC": {"EURUSD", "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURNZD", "EURCAD"},
    "GBP_BLOC": {"GBPUSD", "EURGBP", "GBPJPY", "GBPCHF", "GBPAUD", "GBPNZD", "GBPCAD"},
    "INDEX_US": {"SPX500", "NDX100", "US30", "US2000"},
    "INDEX_EU": {"GER30", "UK100", "FRA40", "EUSTX50", "SWI20"},
}


# ═══════════════════════════════════════════════════════════════
# Utilidades
# ═══════════════════════════════════════════════════════════════

def _atr(velas, period=20):
    if len(velas) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["high"], velas[i]["low"], velas[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return mean(trs[-period:])


def _pip_size(symbol):
    s = symbol.upper()
    if s.startswith(("XAU", "XAG", "XPT")):
        return 0.01
    if "JPY" in s:
        return 0.01
    if s in ("SPX500", "NDX100", "NTH25", "US2000"):
        return 0.1
    if s in ("AUS200", "EUSTX50", "FRA40", "GER30", "HK50",
             "SWI20", "UK100", "US30", "JP225"):
        return 1.0
    if s in ("UKOUSD", "USOUSD"):
        return 0.01
    return 0.0001


def _pip_value_per_lot(symbol):
    s = symbol.upper()
    if s.startswith("XAU"):
        return 1.0
    if s.startswith(("XAG", "XPT")):
        return 5.0
    if s in ("UKOUSD", "USOUSD"):
        return 1.0
    if "JPY" in s:
        return 6.8
    if s in ("SPX500", "NDX100", "NTH25", "US2000",
             "AUS200", "EUSTX50", "FRA40", "GER30", "HK50",
             "SWI20", "UK100", "US30", "JP225"):
        return 1.0
    return 10.0


def _calc_lotaje(symbol, entry, sl, balance, risk_pct=0.002):
    distancia = abs(entry - sl)
    if distancia <= 0:
        return 0.0
    pips = distancia / _pip_size(symbol)
    valor_pip = _pip_value_per_lot(symbol)
    riesgo_usd = balance * risk_pct
    lotaje = riesgo_usd / (pips * valor_pip)
    return round(max(lotaje, 0.01), 2)


# ═══════════════════════════════════════════════════════════════
# Veredicto macro (con caché)
# ═══════════════════════════════════════════════════════════════

def _veredicto_macro(symbol: str) -> dict:
    """Consulta el agente fundamental con caché de 1 hora."""
    ahora = time.time()
    if symbol in _macro_cache:
        cached = _macro_cache[symbol]
        if ahora - cached["ts"] < _MACRO_TTL:
            return cached["data"]

    try:
        from agents import agent_fundamental
        from news_feed import build_fundamental_context

        try:
            bloqueado, motivo = ventana_bloqueada(symbol)
        except Exception:
            bloqueado, motivo = False, ""

        if bloqueado:
            result = {"veredicto": "NO_TRADE", "confianza": 0,
                      "razon": f"Noticia bloqueante: {motivo}"}
            _macro_cache[symbol] = {"ts": ahora, "data": result}
            return result

        try:
            ctx = build_fundamental_context(symbol)
            b = agent_fundamental.run(symbol, ctx)
        except Exception as e:
            result = {"veredicto": "NEUTRAL", "confianza": 0,
                      "razon": f"Error fundamental: {e}"}
            _macro_cache[symbol] = {"ts": ahora, "data": result}
            return result

        veredicto = b.get("veredicto", "NEUTRAL")
        if veredicto not in ("BULLISH", "BEARISH", "NEUTRAL", "NO_TRADE"):
            veredicto = "NEUTRAL"

        razon = b.get("razon", "").lower()
        if veredicto == "NO_TRADE":
            palabras_sin_datos = [
                "sin datos", "no disponible", "caído", "caido",
                "vacío", "vacio", "sin calendario", "sin titulares",
                "no hay datos", "sin información", "sin informacion",
                "no se pudo", "módulo temporal caído", "modulo temporal caido",
            ]
            if any(p in razon for p in palabras_sin_datos):
                veredicto = "NEUTRAL"

        result = {
            "veredicto": veredicto,
            "confianza": b.get("confianza", 0),
            "razon": b.get("razon", ""),
            "catalizador": b.get("catalizador_principal", ""),
        }
        _macro_cache[symbol] = {"ts": ahora, "data": result}
        return result
    except Exception as e:
        log.warning(f"[{symbol}] Error general macro: {e}")
        return {"veredicto": "NEUTRAL", "confianza": 0, "razon": f"Error: {e}"}


# ═══════════════════════════════════════════════════════════════
# Detección de MTF (H4, H1, M15, M5)
# ═══════════════════════════════════════════════════════════════

def _detectar_mtf(velas_por_tf, symbol):
    """Detecta patrones de alineación multi-timeframe."""
    h4 = velas_por_tf.get("H4", [])
    h1 = velas_por_tf.get("H1", [])
    m15 = velas_por_tf.get("M15", [])
    m5 = velas_por_tf.get("M5", [])

    if not all([len(h4) >= 60, len(h1) >= 60, len(m15) >= 60, len(m5) >= 60]):
        return None

    try:
        from strategies.mtf_alignment import run as mtf_run
        mtf_velas = {"H4": h4, "H1": h1, "M15": m15, "M5": m5}
        return mtf_run(mtf_velas, symbol, {})
    except Exception as e:
        log.debug(f"[{symbol}] MTF error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# Evaluación de un par (10 estrategias + HTF + MTF)
# ═══════════════════════════════════════════════════════════════

def _evaluar_par(symbol, velas_por_tf, balance=50000.0,
                 usar_fundamental=True, min_confluencia=2):
    """
    Evalúa un par con las 10 estrategias + HTF + MTF.
    Retorna dict con la mejor señal o None.
    """
    cfg = get_config(symbol)
    if not cfg:
        return None

    try:
        bloqueado, motivo = ventana_bloqueada(symbol)
        if bloqueado:
            return None
    except Exception:
        pass

    señales = []

    # ═══ ESTRATEGIAS D1 ═══
    d1 = velas_por_tf.get("D1", [])
    if len(d1) >= 60:
        for fn, name in [
            (fozzy, "fozzy"),
            (turtle, "turtle"),
            (larry, "larry"),
            (bollinger_breakout, "bollinger_breakout"),
            (ma_crossover, "ma_crossover"),
        ]:
            try:
                s = fn(d1, symbol, cfg.__dict__)
                if s:
                    señales.append({**s, "tf": "D1", "fuente": name})
            except Exception as e:
                log.debug(f"[{symbol}] {name} D1 error: {e}")

    # ═══ ESTRATEGIAS H4 ═══
    h4 = velas_por_tf.get("H4", [])
    if len(h4) >= 60:
        for fn, name in [
            (bollinger_breakout, "bollinger_breakout"),
            (ma_crossover, "ma_crossover"),
            (macd_signal, "macd_signal"),
            (rsi_divergence, "rsi_divergence"),
            (trullas_macd_triple_divergence, "trullas"),
        ]:
            try:
                s = fn(h4, symbol, cfg.__dict__)
                if s:
                    señales.append({**s, "tf": "H4", "fuente": name})
            except Exception as e:
                log.debug(f"[{symbol}] {name} H4 error: {e}")

    # ═══ ESTRATEGIAS H1 ═══
    h1 = velas_por_tf.get("H1", [])
    if len(h1) >= 60:
        for fn, name in [
            (macd_signal, "macd_signal"),
            (rsi_divergence, "rsi_divergence"),
            (rsi2_bb, "rsi2_bb"),
            (trullas_macd_triple_divergence, "trullas"),
        ]:
            try:
                s = fn(h1, symbol, cfg.__dict__)
                if s:
                    señales.append({**s, "tf": "H1", "fuente": name})
            except Exception as e:
                log.debug(f"[{symbol}] {name} H1 error: {e}")

    # ═══ ESTRATEGIAS M15 ═══
    m15 = velas_por_tf.get("M15", [])
    if len(m15) >= 60:
        try:
            s = order_flow(m15, symbol, cfg.__dict__)
            if s:
                señales.append({**s, "tf": "M15", "fuente": "order_flow"})
        except Exception:
            pass
        try:
            s = trullas_macd_triple_divergence(m15, symbol, cfg.__dict__)
            if s:
                señales.append({**s, "tf": "M15", "fuente": "trullas"})
        except Exception:
            pass

    # ═══ ESTRATEGIAS M5 ═══
    m5 = velas_por_tf.get("M5", [])
    if len(m5) >= 90:
        try:
            s = trullas_macd_triple_divergence(m5, symbol, cfg.__dict__)
            if s:
                señales.append({**s, "tf": "M5", "fuente": "trullas"})
        except Exception:
            pass

    # ═══ HTF PULLBACK ═══
    if len(h4) >= 60 and len(h1) >= 60:
        try:
            from htf_structure_v2 import analizar
            est = analizar(symbol, h1, h4)
            if est:
                h1_state = est["h1"].get("state")
                h1_dir = est["h1"].get("trend_direction")
                if h1_state in ("PULLBACK_AT_KEY_ZONE", "PULLBACK_ENDING") and h1_dir:
                    entry = h1[-1]["close"]
                    atr_v = _atr(h1, 14)
                    sl = entry - atr_v * 2 if h1_dir == "LONG" else entry + atr_v * 2
                    risk = abs(entry - sl)
                    tp = entry + risk * 2 if h1_dir == "LONG" else entry - risk * 2
                    señales.append({
                        "strategy": "htf_pullback", "direction": h1_dir,
                        "entry": entry, "sl": round(sl, 5), "tp": round(tp, 5),
                        "confidence": 65, "tf": "H4/H1", "fuente": "htf",
                    })
        except Exception:
            pass

    # ═══ MTF ALIGNMENT ═══
    mtf = _detectar_mtf(velas_por_tf, symbol)
    if mtf:
        señales.append({**mtf, "tf": "MTF", "fuente": "mtf"})

    if not señales:
        return None

    # ═══ Agrupar por dirección ═══
    longs = [s for s in señales if s["direction"] == "LONG"]
    shorts = [s for s in señales if s["direction"] == "SHORT"]

    if len(longs) > len(shorts):
        direccion = "LONG"
        grupo = longs
    elif len(shorts) > len(longs):
        direccion = "SHORT"
        grupo = shorts
    else:
        return None

    confluencia = len(grupo)
    if confluencia < min_confluencia:
        return None

    # ═══ Filtro fundamental ═══
    macro = {"veredicto": "NEUTRAL", "confianza": 0, "razon": "No consultado"}
    if usar_fundamental:
        macro = _veredicto_macro(symbol)
        if macro["veredicto"] == "NO_TRADE":
            return None
        if macro["veredicto"] == "BULLISH" and direccion != "LONG":
            return None
        if macro["veredicto"] == "BEARISH" and direccion != "SHORT":
            return None

    # ═══ Calcular entrada, SL, TP, lotaje ═══
    ultima_vela = (h1[-1] if h1 else d1[-1])
    entry = ultima_vela["close"]

    if direccion == "LONG":
        sl = max(s["sl"] for s in grupo)
        tp = max(s["tp"] for s in grupo)
    else:
        sl = min(s["sl"] for s in grupo)
        tp = min(s["tp"] for s in grupo)

    lotaje = _calc_lotaje(symbol, entry, sl, balance)

    score_tecnico = confluencia * 20 + (sum(s.get("confidence", 50) for s in grupo) / confluencia) * 0.20
    score_macro = macro.get("confianza", 0) * 0.3
    score = min(100, score_tecnico + score_macro)

    return {
        "symbol": symbol,
        "direction": direccion,
        "entry": round(entry, 5),
        "sl": round(sl, 5),
        "tp": round(tp, 5),
        "lotaje": lotaje,
        "confluencia": confluencia,
        "estrategias": [s["fuente"] for s in grupo],
        "timeframes": list(set(s["tf"] for s in grupo)),
        "score": round(score, 1),
        "riesgo_usd": round(abs(entry - sl) / _pip_size(symbol) * _pip_value_per_lot(symbol) * lotaje, 2),
        "rr": round(abs(tp - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0,
        "macro": macro,
    }


# ═══════════════════════════════════════════════════════════════
# Filtro de correlación (evita trades en pares correlacionados)
# ═══════════════════════════════════════════════════════════════

def _filtrar_correlacion(oportunidades, max_por_grupo=1):
    """
    Filtra oportunidades para que no haya más de `max_por_grupo`
    por grupo de correlación. Prioriza las de mayor score.
    """
    if not oportunidades:
        return oportunidades

    # Ordenar por score descendente
    oportunidades.sort(key=lambda x: x["score"], reverse=True)

    seleccionadas = []
    grupos_usados = {}

    for op in oportunidades:
        symbol = op["symbol"]
        grupo_op = None

        for grupo_nombre, miembros in CORRELATION_GROUPS.items():
            if symbol in miembros:
                grupo_op = grupo_nombre
                break

        if grupo_op is None:
            seleccionadas.append(op)
            continue

        usados = grupos_usados.get(grupo_op, 0)
        if usados < max_por_grupo:
            seleccionadas.append(op)
            grupos_usados[grupo_op] = usados + 1
        else:
            log.debug(f"[{symbol}] Descartado por correlación en grupo {grupo_op}")

    return seleccionadas


# ═══════════════════════════════════════════════════════════════
# Scan all (con score mínimo y correlación)
# ═══════════════════════════════════════════════════════════════

def scan_all(velas_por_symbol, balance=50000.0, min_confluencia=2, top_n=3,
             usar_fundamental=True, score_minimo=0, filtrar_correlacion=True):
    """
    Escanea todos los pares, filtra por score mínimo y correlación.
    Usa argumentos NOMBRADOS para evitar bugs de orden.
    """
    oportunidades = []

    for symbol in supported_symbols():
        velas = velas_por_symbol.get(symbol)
        if not velas:
            continue
        try:
            op = _evaluar_par(
                symbol=symbol,
                velas_por_tf=velas,
                balance=balance,
                usar_fundamental=usar_fundamental,
                min_confluencia=min_confluencia,
            )
            if op and op["score"] >= score_minimo:
                oportunidades.append(op)
        except Exception as e:
            log.warning(f"[{symbol}] Error en scan_all: {e}")

    # Filtrar por correlación
    if filtrar_correlacion:
        oportunidades = _filtrar_correlacion(oportunidades, max_por_grupo=1)

    # Ordenar por score
    oportunidades.sort(key=lambda x: x["score"], reverse=True)
    return oportunidades[:top_n]


def run(velas_por_symbol, balance=50000.0, top_n=3, usar_fundamental=True,
        min_confluencia=2, score_minimo=0, filtrar_correlacion=True):
    """
    Función principal. Devuelve las top N oportunidades.
    Usa argumentos NOMBRADOS para evitar bugs de orden.
    """
    return scan_all(
        velas_por_symbol=velas_por_symbol,
        balance=balance,
        min_confluencia=min_confluencia,
        top_n=top_n,
        usar_fundamental=usar_fundamental,
        score_minimo=score_minimo,
        filtrar_correlacion=filtrar_correlacion,
    )
