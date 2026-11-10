# htf_pullback_service.py
"""Servicio HTF (cada 5 min). LOCAL: usa 127.0.0.1."""
import asyncio, json, logging, os
from datetime import datetime, timedelta
from htf_structure_v2 import analizar
from agents import agent_htf_pullback
from mt5_ohlc_client import OHLCSubscriber
from symbol_config import supported_symbols
from config import ZMQ_PC_IP

log = logging.getLogger("htf")
STATE_FILE = "data/htf_state.json"
INTERVAL = 300
TTL_MIN = 60


async def run_forever():
    ohlc = OHLCSubscriber(host=ZMQ_PC_IP)
    log.info("[htf] servicio iniciado (local)")
    while True:
        try:
            resultados = {}
            for sym in supported_symbols():
                data = ohlc.get_full(sym)
                if not data: continue
                h1 = data.get("h1_velas", [])
                h4 = data.get("h4_velas", [])
                if not h1 or not h4: continue
                est = analizar(sym, h1, h4)
                if not est: continue
                h1s = est["h1"].get("state")
                h4s = est["h4"].get("state")
                relevante = h1s in ("PULLBACK_STARTING", "PULLBACK_IN_PROGRESS",
                                     "PULLBACK_AT_KEY_ZONE", "PULLBACK_ENDING",
                                     "REVERSAL_SIGNAL") or \
                             h4s in ("PULLBACK_AT_KEY_ZONE", "REVERSAL_SIGNAL")
                if not relevante: continue
                try:
                    val = agent_htf_pullback.run(est)
                except Exception as e:
                    log.warning(f"LLM falló {sym}: {e}")
                    continue
                merged = {**est, **val,
                          "expira": (datetime.utcnow() + timedelta(minutes=TTL_MIN)).isoformat()}
                resultados[sym] = merged
                log.info(f"[htf] {sym}: H1={h1s} H4={h4s} → {val.get('recomendacion')}")
            _publicar(resultados)
        except Exception as e:
            log.error(f"[htf] error: {e}")
        await asyncio.sleep(INTERVAL)


def _publicar(nuevos):
    os.makedirs("data", exist_ok=True)
    actuales = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                actuales = json.load(f).get("symbols", {})
        except Exception: pass
    ahora = datetime.utcnow()
    actuales.update(nuevos)
    actuales = {s: m for s, m in actuales.items()
                if datetime.fromisoformat(m["expira"]) > ahora}
    with open(STATE_FILE, "w") as f:
        json.dump({"updated_at": ahora.isoformat(), "symbols": actuales}, f, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(run_forever())