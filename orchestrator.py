# orchestrator.py
"""
Orquestador profesional FNL:004 con cazador de oportunidades y alertas locales.
- Jerarquía: fundamental → técnico → consenso.
- Modo manual: notifica a Telegram Y dashboard (no envía al EA).
- Cazador: escanea todos los pares cada ciclo.
- Alertas locales: guardadas en SQLite para el dashboard.
"""
import asyncio
import json
import logging
import os
from datetime import datetime

from agents import (agent_trader, agent_fundamental, agent_technical,
                    agent_adversary, agent_htf_pullback, agent_strategies,
                    agent_opportunity_hunter)
from consensus_v2 import consenso_v2
from fundednext_rules import validar_orden_fnl004, calc_lotage
from profit_tracker import ProfitTracker
from state_manager import (load, save, update_from_mt5,
                            ea_vivo, registrar_heartbeat)
from zmq_bridge import StateSubscriber
from context_builder import (build_market_context, build_technical_context,
                              build_profit_context)
from news_feed import build_fundamental_context, ventana_bloqueada
from config import (SYMBOLS, SYMBOLS_SESSION_ONLY, SESSION_ENABLED,
                    SESSION_START_UTC, SESSION_END_UTC,
                    NO_OPERATE_FRIDAY_AFTER_UTC, MAX_DAILY_PROFIT_USD,
                    INITIAL_BALANCE, ZMQ_PC_IP, MIN_SCORE_CONSENSUS,
                    MIN_CONFLUENCIA, SCORE_MINIMO, FILTRAR_CORRELACION)
from notifier import (start as start_notifier, stop as stop_notifier,
                       notify, notify_signal_local, notify_opportunity_local,
                       notify_ea_status, notify_risk_alert,
                       notify_daily_summary)
from ea_monitor import start as start_ea_monitor
import journal

log = logging.getLogger("orchestrator")
HTF_STATE = "data/htf_state.json"


# ═══════════════════════════════════════════════════════════════
# Utilidades
# ═══════════════════════════════════════════════════════════════

def _cargar_htf(symbol: str) -> dict | None:
    if not os.path.exists(HTF_STATE):
        return None
    try:
        with open(HTF_STATE) as f:
            data = json.load(f)
        m = data.get("symbols", {}).get(symbol)
        if not m:
            return None
        if datetime.fromisoformat(m["expira"]) < datetime.utcnow():
            return None
        return m
    except Exception:
        return None


def _sesion_valida(symbol: str) -> bool:
    if not SESSION_ENABLED:
        return True
    ahora = datetime.utcnow()
    hora = ahora.hour
    if symbol in SYMBOLS_SESSION_ONLY:
        start, end = SYMBOLS_SESSION_ONLY[symbol]
        if not (start <= hora < end):
            return False
    if not (SESSION_START_UTC <= hora < SESSION_END_UTC):
        return False
    if ahora.weekday() == 4 and hora >= NO_OPERATE_FRIDAY_AFTER_UTC:
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# Pipeline por símbolo (consenso de 9 capas)
# ═══════════════════════════════════════════════════════════════

async def procesar_symbol(symbol: str, profit_tracker: ProfitTracker):
    if not _sesion_valida(symbol):
        return None

    snap = profit_tracker.snapshot()
    if snap["objetivo_alcanzado"]:
        log.info(f"[{symbol}] Objetivo diario alcanzado, skip")
        return None
    if snap["ratio_consistencia"] >= 20.0:
        log.warning(f"[{symbol}] Consistency {snap['ratio_consistencia']:.1f}% ≥ 20%. NO OPERAR.")
        return None

    ctx_profit = build_profit_context(snap)

    # ═══ 0. VENTANA DE NOTICIAS (veto duro, antes de gastar tokens) ═══
    try:
        bloqueado, motivo_noticia = ventana_bloqueada(symbol)
    except Exception as e:
        log.warning(f"[{symbol}] Chequeo de noticias falló: {e}")
        bloqueado, motivo_noticia = False, ""
    if bloqueado:
        log.info(f"[{symbol}] ⛔ BLOQUEADO POR NOTICIA: {motivo_noticia}")
        return None

    # ═══ 1. FUNDAMENTAL PRIMERO ═══
    try:
        ctx_fund = build_fundamental_context(symbol) + "\n\n" + ctx_profit
        b = await asyncio.to_thread(agent_fundamental.run, symbol, ctx_fund)
    except Exception as e:
        log.error(f"[{symbol}] Fundamental falló: {e}")
        return None

    veredicto = b.get("veredicto", "NEUTRAL")
    log.info(f"[{symbol}] Macro: {veredicto} (conf {b.get('confianza', 0)}) — {b.get('razon', '')[:80]}")

    if veredicto == "NO_TRADE" or b.get("bloqueado_por_noticia"):
        log.info(f"[{symbol}] VETO FUNDAMENTAL: NO OPERAR")
        return None

    # ═══ 2. TÉCNICO ═══
    ctx_tec = (build_technical_context(symbol) +
               f"\n\nMANDATO MACRO: {veredicto}\n" + ctx_profit)
    try:
        a, c = await asyncio.gather(
            asyncio.to_thread(agent_trader.run, symbol,
                              build_market_context(symbol) + "\n\n" + ctx_profit),
            asyncio.to_thread(agent_technical.run, symbol, ctx_tec, snap),
        )
    except Exception as e:
        log.error(f"[{symbol}] Agentes fallaron: {e}")
        return None

    if c.get("direccion") not in ("LONG", "SHORT"):
        log.info(f"[{symbol}] Técnico no propuso entrada válida")
        return None

    # ═══ 3. ESTRATEGIAS CLÁSICAS ═══
    try:
        from mt5_ohlc_client import OHLCSubscriber
        _ohlc = OHLCSubscriber(host=ZMQ_PC_IP)
        ohlc_data = _ohlc.get_full(symbol) or {}
        velas_por_tf = {
            "D1": ohlc_data.get("d1_velas", []),
            "H4": ohlc_data.get("h4_velas", []),
            "H1": ohlc_data.get("h1_velas", []),
            "M15": ohlc_data.get("m15_velas", []),
            "M5": ohlc_data.get("m5_velas", []),
        }
        strategy_result = agent_strategies.run(symbol, velas_por_tf)
    except Exception as e:
        log.warning(f"[{symbol}] Estrategias fallaron: {e}")
        strategy_result = None

    # ═══ 4. HTF ═══
    htf = _cargar_htf(symbol)
    htf_validation = None
    if htf:
        try:
            htf_validation = agent_htf_pullback.run(htf)
        except Exception as e:
            log.warning(f"[{symbol}] HTF falló: {e}")

    # ═══ 5. ADVERSARIO ═══
    propuesta = {
        "activo": symbol,
        "direccion": c.get("direccion"),
        "entrada": c.get("entrada"),
        "stop_loss": c.get("stop_loss"),
        "take_profit": c.get("take_profit"),
        "veredicto_macro": veredicto,
        "razon_tecnica": c.get("razon"),
    }
    try:
        adversary = agent_adversary.run(propuesta, symbol)
    except Exception:
        adversary = {"objecion_valida": False, "gravedad": 0}

    # ═══ 6. CONSENSO ═══
    cons = consenso_v2(a, b, c, adversary, snap,
                       htf_validation=htf_validation,
                       strategy_result=strategy_result)

    agents_data = {"a": a, "b": b, "c": c, "d": adversary,
                   "htf": htf_validation, "strat": strategy_result}
    dec_id = journal.log_decision(symbol, cons, agents_data, {})

    if not cons["operar"]:
        log.info(f"[{symbol}] NO OPERAR (capa {cons.get('capa')}): {cons['motivo']}")
        return None

    # ═══ 7. SEÑAL + ALERTA (LOCAL + TELEGRAM) ═══
    tec = cons["tecnico"]
    lotaje = calc_lotage(symbol, tec["entrada"], tec["stop_loss"])
    if lotaje <= 0:
        log.warning(f"[{symbol}] Lotaje 0, skip")
        return None

    strat_info = strategy_result.get("consensus", {}) if strategy_result else {}
    estrategia = strat_info.get("used_strategy", "consenso_multiagente")

    signal = {
        "activo": symbol,
        "direccion": tec["direccion"],
        "entrada": tec["entrada"],
        "sl": tec["stop_loss"],
        "tp": tec["take_profit"],
        "lotaje": lotaje,
        "duracion_estimada_min": tec.get("duracion_estimada_min", 30),
        "bloqueado_por_noticia": False,
        "timestamp": datetime.utcnow().isoformat(),
        "score_consenso": cons.get("score"),
        "divergencia_indice": cons.get("divergencia", {}).get("indice")
            if cons.get("divergencia") else None,
        "estrategia": estrategia,
        "veredicto_macro": veredicto,
    }

    state = load()
    ok, motivo = validar_orden_fnl004(signal, state, profit_tracker)
    if not ok:
        log.warning(f"[{symbol}] Rechazada: {motivo}")
        return None

    sig_id = journal.log_signal(dec_id, signal)
    journal.log_rule_check(sig_id, "final_validation", True, 0, 0, "OK")

    # Alerta local + Telegram
    notify_signal_local(signal)
    log.info(f"[{symbol}] 📢 SEÑAL MANUAL | {signal['direccion']} {signal['lotaje']} "
             f"@ {signal['entrada']} | SL: {signal['sl']} | TP: {signal['tp']} "
             f"(score={signal['score_consenso']:.1f})")
    log.info(f"[{symbol}] ⚠️  Ejecuta MANUALMENTE en MT5.")
    return signal


# ═══════════════════════════════════════════════════════════════
# Cazador de oportunidades (escanea TODOS los pares)
# ═══════════════════════════════════════════════════════════════

async def escanear_oportunidades(profit_tracker: ProfitTracker):
    """
    Escanea TODOS los pares con el cazador y notifica las mejores.
    Usa las configuraciones globales: MIN_CONFLUENCIA, SCORE_MINIMO, FILTRAR_CORRELACION.
    """
    from mt5_ohlc_client import OHLCSubscriber
    from symbol_config import supported_symbols

    log.info(f"─── 🎯 Cazador: escaneando {len(supported_symbols())} instrumentos "
             f"(confluencia ≥{MIN_CONFLUENCIA}, score ≥{SCORE_MINIMO}) ───")

    _ohlc = OHLCSubscriber(host=ZMQ_PC_IP)
    velas_por_symbol = {}

    for symbol in supported_symbols():
        data = _ohlc.get_full(symbol, timeout_ms=1000)
        if data and data.get("d1_velas"):
            velas_por_symbol[symbol] = {
                "D1": data.get("d1_velas", []),
                "H4": data.get("h4_velas", []),
                "H1": data.get("h1_velas", []),
                "M15": data.get("m15_velas", []),
                "M5": data.get("m5_velas", []),
            }

    log.info(f"  Datos cargados para {len(velas_por_symbol)} instrumentos")

    if not velas_por_symbol:
        log.warning("  ⚠️ No hay datos de velas. Saltando cazador.")
        return

    st = load()
    balance = st.get("balance", INITIAL_BALANCE)

    try:
        oportunidades = agent_opportunity_hunter.run(
            velas_por_symbol=velas_por_symbol,
            balance=balance,
            top_n=5,
            usar_fundamental=True,
            min_confluencia=MIN_CONFLUENCIA,
            score_minimo=SCORE_MINIMO,
            filtrar_correlacion=FILTRAR_CORRELACION,
        )
    except Exception as e:
        log.error(f"  ❌ Cazador falló: {e}")
        return

    if not oportunidades:
        log.info(f"  🎯 No hay oportunidades con confluencia ≥{MIN_CONFLUENCIA}")
        return

    log.info(f"  🎯 {len(oportunidades)} oportunidad(es) encontrada(s):")
    for i, op in enumerate(oportunidades, 1):
        macro = op.get("macro", {})
        log.info(f"    #{i} {op['symbol']} {op['direction']} | "
                 f"Entrada: {op['entry']} | SL: {op['sl']} | TP: {op['tp']} | "
                 f"Lot: {op['lotaje']} | Confluencia: {op['confluencia']} | "
                 f"Score: {op['score']} | Macro: {macro.get('veredicto')}")

        # Alerta local + Telegram
        notify_opportunity_local(op)


# ═══════════════════════════════════════════════════════════════
# Loop principal
# ═══════════════════════════════════════════════════════════════

async def main_loop():
    journal.init_db()
    start_notifier()
    # Mantiene el heartbeat fresco durante los 15 min de espera. Sin esto,
    # el dashboard marcaba el EA como desconectado aunque siguiera publicando.
    start_ea_monitor()
    sub = StateSubscriber()
    profit_tracker = ProfitTracker.load("default", INITIAL_BALANCE)
    await asyncio.sleep(2)

    log.info("═══ ORQUESTADOR PROFESIONAL FNL:004 ═══")
    log.info(f"Modo: TRADING MANUAL (sin EA)")
    log.info(f"Jerarquía: Fundamental → Técnico → Consenso")
    log.info(f"Símbolos: {SYMBOLS}")
    log.info(f"Cazador: {len(__import__('symbol_config').supported_symbols())} instrumentos")
    log.info(f"Filtros: confluencia ≥{MIN_CONFLUENCIA}, score ≥{SCORE_MINIMO}")
    log.info(f"Correlación: {'ON' if FILTRAR_CORRELACION else 'OFF'}")

    notify("INFO",
           f"🟢 Orquestador iniciado\n"
           f"📊 Modo: TRADING MANUAL\n"
           f"🏛️ Jerarquía: Fundamental → Técnico → Consenso\n"
           f"🎯 Cazador: escaneando todos los instrumentos",
           dedup_key="startup")

    ea_was_offline = True

    while True:
        try:
            # ── Procesar mensajes del EA ──
            while True:
                msg = sub.recv(timeout_ms=50)
                if not msg:
                    break
                registrar_heartbeat(msg)
                update_from_mt5(msg)
                equity = msg.get("equity")
                if equity:
                    profit_tracker.actualizar_peak(equity)
                if ea_was_offline:
                    log.info("✓ EA conectado (MT5 publicando datos)")
                    notify_ea_status(True)
                    ea_was_offline = False

            # ── Verificar EA vivo ──
            if not ea_vivo(120):
                if not ea_was_offline:
                    log.warning("⚠ EA offline. Pausando.")
                    notify_ea_status(False)
                    ea_was_offline = True
                await asyncio.sleep(30)
                continue

            # ── 1. Consenso por símbolo ──
            log.info(f"─── Ciclo de análisis: {SYMBOLS} ───")
            for symbol in SYMBOLS:
                try:
                    await procesar_symbol(symbol, profit_tracker)
                except Exception as e:
                    log.error(f"[{symbol}] Error: {e}")

            # ── 2. Cazador de oportunidades ──
            await escanear_oportunidades(profit_tracker)

            # ── 3. Journal equity ──
            st = load()
            journal.log_equity(
                st.get("equity", INITIAL_BALANCE),
                st.get("balance", INITIAL_BALANCE),
                st.get("riesgo_abierto", 0),
                st.get("perdida_hoy", 0),
                st.get("open_positions", 0),
            )

            # ── 4. Alertas de riesgo ──
            perdida = st.get("perdida_hoy", 0)
            limite_dl = INITIAL_BALANCE * 0.02  # 2% operativo
            if perdida > limite_dl * 0.8:
                notify_risk_alert("Pérdida diaria", perdida, limite_dl)

            riesgo = st.get("riesgo_abierto", 0)
            limite_ra = INITIAL_BALANCE * 0.005  # 0.5% operativo
            if riesgo > limite_ra * 0.8:
                notify_risk_alert("Riesgo abierto", riesgo, limite_ra)

            # ── 5. Resumen diario ──
            hora_utc = datetime.utcnow().hour
            minuto_utc = datetime.utcnow().minute
            if hora_utc == 23 and 50 <= minuto_utc <= 55:
                snap = profit_tracker.snapshot()
                notify_daily_summary({
                    "fecha": str(datetime.utcnow().date()),
                    "balance": st.get("balance", INITIAL_BALANCE),
                    "equity": st.get("equity", INITIAL_BALANCE),
                    "pnl_hoy": snap.get("daily_pnl", 0),
                    "pnl_ciclo": snap.get("total_pnl_ciclo", 0),
                    "best_day": snap.get("best_day_pnl", 0),
                    "ratio": snap.get("ratio_consistencia", 0),
                    "trailing_floor": snap.get("trailing_floor", 0),
                    "puede_retirar": snap.get("puede_retirar", False),
                    "motivo_retiro": snap.get("motivo_retiro", ""),
                })

            log.info("─── Ciclo completado. Esperando 15 min ───")
            await asyncio.sleep(900)

        except Exception as e:
            log.error(f"Error en loop: {e}")
            await asyncio.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/orchestrator.log"),
            logging.StreamHandler(),
        ],
    )
    asyncio.run(main_loop())
