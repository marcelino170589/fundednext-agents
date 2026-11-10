# ea_monitor.py
"""
Monitor ZMQ del EA para el dashboard.

El orquestador ya escribe `logs/heartbeat.json` cuando recibe el estado de MT5.
Este monitor permite que la API/dashboard sepa si el EA está publicando aunque
el orquestador esté detenido o reiniciándose. Es un SUB adicional sobre el
mismo puerto; ZMQ PUB/SUB admite varios suscriptores.

No ejecuta órdenes ni interpreta señales: solo actualiza heartbeat y estado.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from state_manager import (
    ea_vivo,
    registrar_heartbeat,
    ultimo_heartbeat,
    update_from_mt5,
)

log = logging.getLogger("ea_monitor")

_STATE = {
    "running": False,
    "last_message_at": None,
    "last_error": None,
    "messages": 0,
    "started_at": None,
    "endpoint": None,
}
_LOCK = threading.RLock()
_THREAD = None
_STOP = threading.Event()


def _enabled() -> bool:
    return os.getenv("EA_MONITOR_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on", "si", "sí",
    )


def _loop():
    global _THREAD
    from config import ZMQ_PC_IP
    from zmq_bridge import StateSubscriber

    endpoint = f"tcp://{ZMQ_PC_IP}:5556"
    with _LOCK:
        _STATE["running"] = True
        _STATE["started_at"] = time.time()
        _STATE["endpoint"] = endpoint
    sub = None
    try:
        sub = StateSubscriber()
        while not _STOP.is_set():
            try:
                msg = sub.recv(1000)
            except Exception as exc:
                with _LOCK:
                    _STATE["last_error"] = str(exc)[:200]
                time.sleep(1.0)
                continue
            if not msg:
                continue
            try:
                registrar_heartbeat(msg)
                update_from_mt5(msg)
                with _LOCK:
                    _STATE["messages"] += 1
                    _STATE["last_message_at"] = time.time()
                    _STATE["last_error"] = None
            except Exception as exc:
                with _LOCK:
                    _STATE["last_error"] = str(exc)[:200]
                log.debug("[ea_monitor] error actualizando estado: %s", exc)
    except Exception as exc:
        with _LOCK:
            _STATE["last_error"] = str(exc)[:300]
        log.warning("[ea_monitor] no se pudo iniciar el SUB ZMQ: %s", exc)
    finally:
        if sub is not None:
            try:
                sub.close()
            except Exception:
                pass
        with _LOCK:
            _STATE["running"] = False
            _THREAD = None
        log.info("[ea_monitor] detenido")


def start() -> bool:
    """Arranca el monitor una sola vez. Devuelve True si quedó activo."""
    global _THREAD
    if not _enabled():
        log.info("[ea_monitor] desactivado por EA_MONITOR_ENABLED=false")
        return False
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return True
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="ea-monitor", daemon=True)
        _THREAD.start()
    log.info("[ea_monitor] monitor ZMQ iniciado")
    return True


def stop(timeout: float = 2.0):
    _STOP.set()
    thread = _THREAD
    if thread:
        thread.join(timeout=timeout)


def get_status() -> dict:
    with _LOCK:
        state = dict(_STATE)
    hb = ultimo_heartbeat() or {}
    state.update({
        "enabled": _enabled(),
        "heartbeat_age_sec": (
            max(0, int(time.time() - float(hb.get("ts", 0))))
            if hb.get("ts") else None
        ),
        "last_seen": hb.get("iso"),
        "alive": bool(ea_vivo(120)),
        "can_receive": bool(state.get("running")),
    })
    return state
