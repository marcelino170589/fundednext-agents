# zmq_bridge.py
"""Puente ZMQ Python ↔ MT5 vía WireGuard."""
import json
import logging
import zmq
from config import ZMQ_SIGNAL_PORT, ZMQ_STATE_PORT, ZMQ_PC_IP

log = logging.getLogger("zmq")


class SignalPublisher:
    """Python (VPS/WSL) → MT5 (PC) (PUB)."""
    def __init__(self):
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.PUB)
        self.sock.bind(f"tcp://*:{ZMQ_SIGNAL_PORT}")
        log.info(f"PUB señales en :{ZMQ_SIGNAL_PORT}")

    def send(self, signal: dict):
        try:
            self.sock.send_string(json.dumps(signal, default=str))
            log.debug(f"Señal enviada: {signal.get('activo')} {signal.get('direccion')}")
        except Exception as e:
            log.error(f"Error enviando: {e}")

    def close(self):
        self.sock.close()
        self.ctx.term()


class StateSubscriber:
    """MT5 (PC) → Python (VPS/WSL) (SUB)."""
    def __init__(self):
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.connect(f"tcp://{ZMQ_PC_IP}:{ZMQ_STATE_PORT}")
        self.sock.setsockopt_string(zmq.SUBSCRIBE, "")
        log.info(f"SUB estado a {ZMQ_PC_IP}:{ZMQ_STATE_PORT}")

    def recv(self, timeout_ms: int = 200) -> dict | None:
        if self.sock.poll(timeout_ms):
            try:
                return json.loads(self.sock.recv_string())
            except json.JSONDecodeError:
                return None
        return None

    def close(self):
        self.sock.close()
        self.ctx.term()