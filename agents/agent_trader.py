# agents/agent_trader.py
from llm_client import ask_json
from prompt_rotator import get_prompt

SYSTEM = """Eres trader institucional con 20 años. Emites SESGO DIRECCIONAL
y CONFIANZA. NO das entradas ni stops. Si no estás seguro, NEUTRAL.

CONTEXTO FNL:004: cuenta 50K, trailing DD $2,000, consistency 20%.
Sé conservador: es mejor no operar que arriesgar el ciclo.

Responde SOLO JSON:
{"activo":"...","sesgo":"LONG|SHORT|NEUTRAL","confianza":0-100,
 "razon_principal":"máx 30 palabras","horizonte":"intradía|swing_corto"}"""

def run(activo, contexto):
    system, variant = get_prompt("trader", activo)
    if not system:
        system = SYSTEM
    out = ask_json(system, f"Activo: {activo}\nContexto:\n{contexto}")
    out["_variant"] = variant
    return out