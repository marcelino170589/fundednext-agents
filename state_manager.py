# state_manager.py
"""Estado con heartbeat y trailing drawdown."""
import json
import os
import time
from datetime import datetime, date
from config import INITIAL_BALANCE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "logs", "state.json")
HEARTBEAT_FILE = os.path.join(BASE_DIR, "logs", "heartbeat.json")


def _default():
    return {
        "fecha": str(date.today()),
        "equity": INITIAL_BALANCE,
        "balance": INITIAL_BALANCE,
        "peak_equity": INITIAL_BALANCE,
        "perdida_hoy": 0.0,
        "riesgo_abierto": 0.0,
        "open_positions": 0,
        "dias_trading": 0,
    }


def load() -> dict:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    if not os.path.exists(STATE_FILE):
        return _default()
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
    except Exception:
        return _default()

    if st.get("fecha") != str(date.today()):
        st["fecha"] = str(date.today())
        st["perdida_hoy"] = 0.0
    st.setdefault("peak_equity", st.get("equity", INITIAL_BALANCE))
    return st


def save(st: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=2)


def update_from_mt5(msg: dict):
    st = load()
    st["equity"] = msg.get("equity", st["equity"])
    st["balance"] = msg.get("balance", st["balance"])
    st["riesgo_abierto"] = msg.get("open_risk", 0.0)
    st["open_positions"] = msg.get("open_positions", 0)
    st["perdida_hoy"] = max(0.0, st["balance"] - st["equity"])
    # Actualizar peak
    if st["equity"] > st.get("peak_equity", INITIAL_BALANCE):
        st["peak_equity"] = st["equity"]
    save(st)


def registrar_heartbeat(msg: dict):
    os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
    data = {
        "ts": time.time(),
        "account": msg.get("account"),
        "balance": msg.get("balance"),
        "equity": msg.get("equity"),
        "open_positions": msg.get("open_positions", 0),
        "iso": datetime.utcnow().isoformat(),
    }
    with open(HEARTBEAT_FILE, "w") as f:
        json.dump(data, f)


def ea_vivo(timeout_seg: int = 120) -> bool:
    if not os.path.exists(HEARTBEAT_FILE):
        return False
    try:
        with open(HEARTBEAT_FILE) as f:
            data = json.load(f)
        return (time.time() - data.get("ts", 0)) < timeout_seg
    except Exception:
        return False


def ultimo_heartbeat() -> dict | None:
    if not os.path.exists(HEARTBEAT_FILE):
        return None
    try:
        with open(HEARTBEAT_FILE) as f:
            return json.load(f)
    except Exception:
        return None