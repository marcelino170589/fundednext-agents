# notifier.py
"""
Notificador de alertas para FNL:004.

- Dashboard local: siempre escribe en SQLite.
- Telegram: cola en segundo plano, mensajes completos, división en chunks
  (límite 4096 de Telegram), reintentos, rate-limit y deduplicación.

El objetivo es que Telegram reciba TODO el contexto de una señal/oportunidad,
no solo una línea resumen. Si el mensaje supera el límite, se envía en varias
partes numeradas. El worker nunca bloquea el ciclo de trading.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone

import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_ENABLED,
    TELEGRAM_MIN_SEVERITY,
    TELEGRAM_RATE_LIMIT_SECONDS,
    TELEGRAM_DEDUPE_SECONDS,
    TELEGRAM_MAX_CHARS,
)

log = logging.getLogger("notifier")

SEVERITY_LEVELS = {"INFO": 1, "WARNING": 2, "CRITICAL": 3}
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_state = {
    "enabled": bool(TELEGRAM_ENABLED and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
    "configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
    "worker": None,
    "queue": queue.Queue(maxsize=500),
    "stop_event": threading.Event(),
    "last_sent_at": None,
    "last_error": None,
    "sent": 0,
    "failed": 0,
    "dropped": 0,
    "dedupe": {},
    "lock": threading.RLock(),
}


# ═══════════════════════════════════════════════════════════════
# Formato de mensajes
# ═══════════════════════════════════════════════════════════════

def _v(value, default="—"):
    if value is None or value == "":
        return default
    return str(value)


def _num(value, digits=5):
    try:
        number = float(value)
        return f"{number:.{digits}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return _v(value)


def _money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return _v(value)


def _pct(value):
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return _v(value)


def _price(value):
    """Precio legible sin notación científica."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _v(value)
    if abs(number) >= 1000:
        return f"{number:,.2f}"
    if abs(number) >= 10:
        return f"{number:,.3f}".rstrip("0").rstrip(".")
    return f"{number:,.5f}".rstrip("0").rstrip(".")


def _list(value):
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if item)
    if isinstance(value, str):
        return value
    return "—"


def _ts(value=None):
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text = str(value)
    return text.replace("T", " ")[:19] + " UTC" if len(text) >= 19 else text


def _macro_text(macro) -> list[str]:
    if not isinstance(macro, dict) or not macro:
        return []
    lines = []
    if macro.get("veredicto"):
        lines.append(f"Macro: {macro['veredicto']} (confianza {_v(macro.get('confianza'))})")
    if macro.get("razon"):
        lines.append(f"Razón macro: {macro['razon']}")
    if macro.get("catalizador"):
        lines.append(f"Catalizador: {macro['catalizador']}")
    return lines


def format_signal(signal: dict) -> str:
    """Mensaje completo de una señal del consenso de 9 capas."""
    if not isinstance(signal, dict):
        return str(signal)

    direction = signal.get("direccion") or signal.get("direction") or "—"
    symbol = signal.get("activo") or signal.get("symbol") or "—"
    entry = signal.get("entrada", signal.get("entry"))
    sl = signal.get("sl", signal.get("stop_loss"))
    tp = signal.get("tp", signal.get("take_profit"))
    lot = signal.get("lotaje", signal.get("lotage"))
    risk = signal.get("riesgo_usd", signal.get("risk_usd"))
    rr = signal.get("rr")

    lines = [
        "🚨 FNL:004 · SEÑAL MANUAL",
        "────────────────────────",
        f"Activo: {_v(symbol)}",
        f"Dirección: {_v(direction)}",
        f"Entrada: {_price(entry)}",
        f"Stop Loss: {_price(sl)}",
        f"Take Profit: {_price(tp)}",
        f"Lote: {_v(lot)}",
    ]
    if rr is not None:
        lines.append(f"R:R: 1:{_num(rr, 2)}")
    if risk is not None:
        lines.append(f"Riesgo estimado: {_money(risk)}")
    if signal.get("score_consenso") is not None:
        lines.append(f"Score consenso: {_num(signal.get('score_consenso'), 1)}")
    if signal.get("confluencia") is not None:
        lines.append(f"Confluencia: {_v(signal.get('confluencia'))}")
    if signal.get("estrategia"):
        lines.append(f"Estrategia: {_v(signal.get('estrategia'))}")
    if signal.get("timeframes"):
        lines.append(f"Timeframes: {_list(signal.get('timeframes'))}")
    if signal.get("duracion_estimada_min") is not None:
        lines.append(f"Duración estimada: {_v(signal.get('duracion_estimada_min'))} min")
    if signal.get("divergencia_indice") is not None:
        lines.append(f"Divergencia: {_num(signal.get('divergencia_indice'), 1)}")
    if signal.get("veredicto_macro"):
        lines.append(f"Veredicto macro: {_v(signal.get('veredicto_macro'))}")
    lines.extend(_macro_text(signal.get("macro")))

    if signal.get("razon") or signal.get("razon_tecnica"):
        lines.append(f"Razón: {_v(signal.get('razon') or signal.get('razon_tecnica'))}")
    if signal.get("timestamp"):
        lines.append(f"Generado: {_ts(signal.get('timestamp'))}")

    lines.extend([
        "────────────────────────",
        "⚠️ Ejecución manual en MT5.",
        "Verifica precio, spread y tamaño antes de operar.",
    ])
    return "\n".join(lines)


def format_opportunity(op: dict) -> str:
    """Mensaje completo de una oportunidad del cazador."""
    if not isinstance(op, dict):
        return str(op)

    symbol = op.get("symbol") or op.get("activo") or "—"
    direction = op.get("direction") or op.get("direccion") or "—"
    lines = [
        "🎯 FNL:004 · OPORTUNIDAD",
        "────────────────────────",
        f"Activo: {_v(symbol)}",
        f"Dirección: {_v(direction)}",
        f"Entrada: {_price(op.get('entry', op.get('entrada')))}",
        f"Stop Loss: {_price(op.get('sl', op.get('stop_loss')))}",
        f"Take Profit: {_price(op.get('tp', op.get('take_profit')))}",
        f"Lote: {_v(op.get('lotaje', op.get('lotage')))}",
    ]
    if op.get("rr") is not None:
        lines.append(f"R:R: 1:{_num(op.get('rr'), 2)}")
    if op.get("riesgo_usd") is not None:
        lines.append(f"Riesgo estimado: {_money(op.get('riesgo_usd'))}")
    if op.get("confluencia") is not None:
        lines.append(f"Confluencia: {_v(op.get('confluencia'))}")
    if op.get("score") is not None:
        lines.append(f"Score: {_num(op.get('score'), 1)}")
    if op.get("estrategias"):
        lines.append(f"Estrategias: {_list(op.get('estrategias'))}")
    if op.get("timeframes"):
        lines.append(f"Timeframes: {_list(op.get('timeframes'))}")
    if op.get("macro"):
        lines.extend(_macro_text(op.get("macro")))
    if op.get("razon"):
        lines.append(f"Razón: {_v(op.get('razon'))}")
    if op.get("ts") or op.get("timestamp"):
        lines.append(f"Generado: {_ts(op.get('ts') or op.get('timestamp'))}")
    lines.extend([
        "────────────────────────",
        "⚠️ Ejecución manual. No es una orden.",
    ])
    return "\n".join(lines)


def format_daily_summary(stats: dict) -> str:
    if not isinstance(stats, dict):
        return str(stats)
    lines = ["📊 FNL:004 · RESUMEN DIARIO", "────────────────────────"]
    for key, label in (
        ("fecha", "Fecha"),
        ("balance", "Balance"),
        ("equity", "Equity"),
        ("pnl_hoy", "P&L hoy"),
        ("pnl_ciclo", "P&L ciclo"),
        ("best_day", "Mejor día"),
        ("ratio", "Consistency"),
        ("trailing_floor", "Trailing floor"),
        ("puede_retirar", "Puede retirar"),
        ("motivo_retiro", "Motivo retiro"),
    ):
        if key not in stats:
            continue
        value = stats.get(key)
        if key in ("balance", "equity", "pnl_hoy", "pnl_ciclo", "best_day", "trailing_floor"):
            value = _money(value)
        elif key == "ratio":
            value = _pct(value)
        lines.append(f"{label}: {_v(value)}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Cola / deduplicación / rate-limit
# ═══════════════════════════════════════════════════════════════

def _severity_ok(severity: str) -> bool:
    return SEVERITY_LEVELS.get(str(severity).upper(), 1) >= SEVERITY_LEVELS.get(
        str(TELEGRAM_MIN_SEVERITY).upper(), 1
    )


def _dedupe_seen(key: str | None) -> bool:
    if not key:
        return False
    now = time.time()
    with _state["lock"]:
        # Limpieza oportunista.
        expired = [k for k, ts in _state["dedupe"].items() if now - ts > TELEGRAM_DEDUPE_SECONDS]
        for k in expired:
            _state["dedupe"].pop(k, None)
        if key in _state["dedupe"]:
            return True
        _state["dedupe"][key] = now
        return False


def _split_message(text: str) -> list[str]:
    """Divide respetando líneas y el límite de Telegram (4096)."""
    text = str(text or "").strip()
    if not text:
        return []
    limit = max(200, min(4096, int(TELEGRAM_MAX_CHARS)))
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        # Una línea individual demasiado larga se corta en trozos.
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)

    total = len(chunks)
    return [f"[{i + 1}/{total}]\n{chunk}" for i, chunk in enumerate(chunks)]


def _wait_rate_limit():
    last = _state.get("last_sent_at")
    if last:
        delay = float(TELEGRAM_RATE_LIMIT_SECONDS) - (time.time() - last)
        if delay > 0:
            time.sleep(delay)


def _send_raw(text: str) -> bool:
    url = _TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    for attempt in range(1, 4):
        try:
            response = requests.post(url, json=payload, timeout=20)
            data = {}
            try:
                data = response.json()
            except Exception:
                pass
            if response.status_code == 200 and data.get("ok"):
                return True
            if response.status_code == 429:
                retry_after = int((data.get("parameters") or {}).get("retry_after", 5))
                retry_after = max(1, min(30, retry_after))
                log.warning("[notifier] Telegram 429; reintento en %ss", retry_after)
                time.sleep(retry_after)
                continue
            if response.status_code >= 500:
                time.sleep(1.5 * attempt)
                continue
            error = data.get("description") or f"HTTP {response.status_code}"
            with _state["lock"]:
                _state["last_error"] = error
            log.error("[notifier] Telegram rechazó el mensaje: %s", error)
            return False
        except requests.RequestException as exc:
            with _state["lock"]:
                _state["last_error"] = str(exc)[:300]
            log.warning("[notifier] Error de red Telegram (%s/3): %s", attempt, exc)
            time.sleep(1.5 * attempt)
    return False


def _worker():
    log.info("[notifier] Worker de Telegram iniciado")
    while not _state["stop_event"].is_set():
        try:
            item = _state["queue"].get(timeout=1.0)
        except queue.Empty:
            continue
        if item is None:
            _state["queue"].task_done()
            break
        _wait_rate_limit()
        ok = _send_raw(item["text"])
        with _state["lock"]:
            if ok:
                _state["sent"] += 1
                _state["last_sent_at"] = time.time()
                _state["last_error"] = None
            else:
                _state["failed"] += 1
        if not ok:
            log.error("[notifier] No se pudo enviar a Telegram (chunk %s)", item.get("index"))
        _state["queue"].task_done()
    log.info("[notifier] Worker de Telegram detenido")


def _ensure_worker():
    if not _state["enabled"]:
        return False
    with _state["lock"]:
        worker = _state.get("worker")
        if worker and worker.is_alive():
            return True
        _state["stop_event"].clear()
        worker = threading.Thread(target=_worker, name="telegram-notifier", daemon=True)
        _state["worker"] = worker
        worker.start()
    return True


def get_status() -> dict:
    with _state["lock"]:
        return {
            "enabled": bool(_state["enabled"]),
            "configured": bool(_state["configured"]),
            "queue": _state["queue"].qsize(),
            "sent": _state["sent"],
            "failed": _state["failed"],
            "dropped": _state["dropped"],
            "last_error": _state["last_error"],
            "last_sent_at": (
                datetime.fromtimestamp(_state["last_sent_at"], tz=timezone.utc).isoformat()
                if _state["last_sent_at"] else None
            ),
            "min_severity": TELEGRAM_MIN_SEVERITY,
            "rate_limit_seconds": TELEGRAM_RATE_LIMIT_SECONDS,
            "dedupe_seconds": TELEGRAM_DEDUPE_SECONDS,
        }


# ═══════════════════════════════════════════════════════════════
# API pública
# ═══════════════════════════════════════════════════════════════

def start():
    if not TELEGRAM_ENABLED:
        log.info("[notifier] Telegram desactivado (TELEGRAM_ENABLED=false)")
        return False
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        log.warning("[notifier] Telegram activado pero falta TOKEN o CHAT_ID")
        return False
    _state["enabled"] = True
    _state["configured"] = True
    _ensure_worker()
    log.info("[notifier] Telegram activo (chat %s..., severidad mínima %s)",
             str(TELEGRAM_CHAT_ID)[:4], TELEGRAM_MIN_SEVERITY)
    return True


def stop(timeout=5.0):
    _state["stop_event"].set()
    try:
        _state["queue"].put_nowait(None)
    except queue.Full:
        pass
    worker = _state.get("worker")
    if worker:
        worker.join(timeout=timeout)


def notify(severity, message, dedup_key=None):
    """Encola un mensaje genérico completo para Telegram.

    Devuelve True si se encoló al menos un chunk; False si estaba desactivado,
    filtrado por severidad, duplicado o la cola estaba llena.
    """
    if not _state["enabled"]:
        return False
    if not _severity_ok(severity):
        return False
    if _dedupe_seen(dedup_key):
        return False
    chunks = _split_message(message)
    if not chunks:
        return False
    _ensure_worker()
    queued = 0
    for index, chunk in enumerate(chunks):
        try:
            _state["queue"].put_nowait({"text": chunk, "index": index + 1})
            queued += 1
        except queue.Full:
            with _state["lock"]:
                _state["dropped"] += 1
            log.error("[notifier] Cola de Telegram llena; chunk %s descartado", index + 1)
            break
    return queued > 0


def notify_signal(signal):
    """Envía una señal completa (entrada, SL, TP, lote, score, macro...)."""
    return notify(
        "WARNING", format_signal(signal),
        dedup_key=f"signal:{signal.get('activo') or signal.get('symbol')}:"
                  f"{signal.get('direccion') or signal.get('direction')}:"
                  f"{signal.get('entrada') or signal.get('entry')}",
    )


def notify_opportunity(op):
    """Envía una oportunidad completa del cazador."""
    return notify(
        "WARNING", format_opportunity(op),
        dedup_key=f"opp:{op.get('symbol') or op.get('activo')}:"
                  f"{op.get('direction') or op.get('direccion')}:"
                  f"{op.get('entry') or op.get('entrada')}",
    )


# ═══════════════════════════════════════════════════════════════
# Alertas locales (dashboard) + espejo a Telegram
# ═══════════════════════════════════════════════════════════════

def notify_local(severity, tipo, message, symbol=None, direction=None, data=None):
    """Registra una alerta local para el dashboard."""
    try:
        import journal
        journal.log_local_alert(severity, tipo, message, symbol, direction, data)
    except Exception as exc:
        log.warning("[notifier] Error log_local_alert: %s", exc)


def notify_signal_local(signal):
    """Alerta local + Telegram con todos los datos de la señal."""
    activo = signal.get("activo", "?")
    direccion = signal.get("direccion", "?")
    msg = f"SEÑAL: {activo} {direccion} @ {signal.get('entrada', 0)}"
    notify_local("WARNING", "signal", msg,
                 symbol=activo, direction=direccion, data=signal)
    notify_signal(signal)


def notify_opportunity_local(op):
    """Alerta local + Telegram con todos los datos de la oportunidad."""
    symbol = op.get("symbol", "?")
    direccion = op.get("direction", "?")
    confluencia = op.get("confluencia", 0)
    msg = f"OPORTUNIDAD: {symbol} {direccion} (confluencia {confluencia})"
    notify_local("WARNING", "opportunity", msg,
                 symbol=symbol, direction=direccion, data=op)
    notify_opportunity(op)


def notify_ea_status(online):
    if online:
        notify_local("INFO", "ea_status", "🟢 EA conectado")
        notify("INFO", "🟢 FNL:004 · EA conectado\nEl orquestador ya recibe datos de MT5.",
               dedup_key="ea:online")
    else:
        notify_local("WARNING", "ea_status", "🔴 EA OFFLINE")
        notify("WARNING", "🔴 FNL:004 · EA OFFLINE\nEl orquestador pausa el análisis hasta que vuelva.",
               dedup_key="ea:offline")


def notify_risk_alert(tipo, valor, limite):
    pct = valor / limite * 100 if limite > 0 else 0
    sev = "CRITICAL" if pct >= 90 else "WARNING"
    msg = f"{tipo}: {valor:,.2f} / {limite:,.2f} ({pct:.1f}%)"
    notify_local(sev, "risk", msg,
                 data={"tipo": tipo, "valor": valor, "limite": limite, "pct": pct})
    notify(
        sev,
        f"{'⛔' if sev == 'CRITICAL' else '⚠️'} FNL:004 · RIESGO\n"
        "────────────────────────\n"
        f"{msg}\n"
        f"Uso del límite: {pct:.1f}%",
        dedup_key=f"risk:{tipo}:{round(valor, 2)}:{round(limite, 2)}",
    )


def notify_daily_summary(stats):
    msg = (f"Resumen {stats.get('fecha', '')}: "
           f"P&L hoy ${stats.get('pnl_hoy', 0):+,.2f} | "
           f"Consistency {stats.get('ratio', 0):.1f}%")
    notify_local("INFO", "daily_summary", msg, data=stats)
    notify("INFO", format_daily_summary(stats),
           dedup_key=f"daily:{stats.get('fecha')}")


def send_test_message() -> bool:
    """Envía un mensaje de prueba; usado por /api/telegram/test."""
    return notify(
        "INFO",
        "✅ FNL:004 · prueba de Telegram\n"
        "────────────────────────\n"
        "Si ves este mensaje, el canal está configurado y el worker funciona.\n"
        f"Fecha: {_ts()}",
        dedup_key=None,
    )
