# agents/agent_adversary.py
from llm_client import ask_json
from prompt_rotator import get_prompt

SYSTEM = """Abogado del Diablo. Tu ÚNICO trabajo es RECHAZAR operaciones.
Sé escéptico por defecto.

FNL:004: gravedad ≥4 → rechazar. El trailing DD es implacable.

Responde SOLO JSON:
{"objecion_valida":true|false,"gravedad":1-10,
 "objecion_principal":"máx 40 palabras","objeciones_secundarias":["...","..."]}"""

def run(propuesta, symbol="XAUUSD"):
    system, variant = get_prompt("adversary", symbol)
    if not system:
        system = SYSTEM
    out = ask_json(system, f"PROPUESTA:\n{propuesta}")
    out["_variant"] = variant
    return out