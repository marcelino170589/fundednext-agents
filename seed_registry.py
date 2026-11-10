# seed_registry.py
"""Registro de semillas por cuenta (auditoría multi-cuenta)."""
import json, os
from datetime import datetime

REGISTRY_FILE = "data/seed_registry.json"


def registrar_semilla(account_id, seed_hex, mode, magic_base):
    os.makedirs("data", exist_ok=True)
    data = {}
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE) as f: data = json.load(f)
    data[str(account_id)] = {"seed_hex": seed_hex, "mode": mode,
                              "magic_base": magic_base,
                              "registered_at": datetime.utcnow().isoformat()}
    with open(REGISTRY_FILE, "w") as f: json.dump(data, f, indent=2)


def obtener_semilla(account_id):
    if not os.path.exists(REGISTRY_FILE): return None
    with open(REGISTRY_FILE) as f: return json.load(f).get(str(account_id))


def verificar_independencia():
    if not os.path.exists(REGISTRY_FILE):
        return {"ok": True, "cuentas": 0}
    with open(REGISTRY_FILE) as f: data = json.load(f)
    seeds = [v["seed_hex"] for v in data.values()]
    return {"ok": len(seeds) == len(set(seeds)), "cuentas": len(seeds),
            "duplicadas": len(seeds) - len(set(seeds))}