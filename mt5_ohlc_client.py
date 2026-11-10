# mt5_ohlc_client.py
"""Subscriber ZMQ para OHLC desde MT5 (a través de WireGuard)."""
import json
import logging
import zmq
from config import ZMQ_OHLC_PORT

log = logging.getLogger("ohlc")


class OHLCSubscriber:
    def __init__(self, host: str = "10.8.0.2", port: int = ZMQ_OHLC_PORT):
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.connect(f"tcp://{host}:{port}")
        self.sock.setsockopt_string(zmq.SUBSCRIBE, "")
        self.cache: dict = {}
        log.info(f"OHLC SUB conectado a {host}:{port}")

    def get_full(self, symbol: str, timeout_ms: int = 500) -> dict | None:
        if self.sock.poll(timeout_ms):
            try:
                self.cache = json.loads(self.sock.recv_string())
            except json.JSONDecodeError:
                pass
        return self.cache.get(symbol)

    def get(self, symbol: str, timeout_ms: int = 500) -> dict | None:
        data = self.get_full(symbol, timeout_ms)
        return data.get("h1") if data else None

    def close(self):
        self.sock.close()
        self.ctx.term()