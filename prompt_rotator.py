# prompt_rotator.py
"""Rotación determinista de variantes de prompt."""
import hashlib, json, os
from datetime import datetime
from prompt_variants import CATALOG

USAGE_LOG = "logs/prompt_usage.jsonl"
BLACKLIST_FILE = "logs/prompt_blacklist.json"


def _load_blacklist():
    if not os.path.exists(BLACKLIST_FILE):
        return {}
    try:
        with open(BLACKLIST_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def get_variant(agent, symbol, salt=""):
    if agent not in CATALOG:
        return ""
    variants = CATALOG[agent]
    nombres = list(variants.keys())
    blacklist = _load_blacklist().get(agent, [])
    disponibles = [n for n in nombres if n not in blacklist] or nombres
    semana = datetime.utcnow().isocalendar()
    seed = f"{semana[0]}-{semana[1]}|{agent}|{symbol}|{salt}"
    idx = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(disponibles)
    return disponibles[idx]


def get_prompt(agent, symbol, salt=""):
    v = get_variant(agent, symbol, salt)
    if not v:
        return "", ""
    return CATALOG[agent][v], v


def log_usage(agent, variant, symbol, result=None):
    os.makedirs("logs", exist_ok=True)
    with open(USAGE_LOG, "a") as f:
        f.write(json.dumps({"ts": datetime.utcnow().isoformat(),
                            "agent": agent, "variant": variant,
                            "symbol": symbol, "result": result}) + "\n")


def update_blacklist(agent, variant, motivo):
    bl = _load_blacklist()
    bl.setdefault(agent, [])
    if variant not in bl[agent]:
        bl[agent].append(variant)
        with open(BLACKLIST_FILE, "w") as f:
            json.dump(bl, f, indent=2)