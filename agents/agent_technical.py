# agents/agent_technical.py
"""
Agente Técnico — El Ejecutor.
Recibe el mandato del fundamental y SOLO busca patrones en esa dirección.
Si el fundamental dice BULLISH, solo busca LONG. Si BEARISH, solo SHORT.
"""
from llm_client import ask_json
from prompt_rotator import get_prompt

SYSTEM = """Eres el Jefe de Análisis Técnico de una firma de trading.
Recibirás un MANDATO MACRO del analista fundamental (BULLISH, BEARISH o NO_TRADE).

REGLAS ESTRICTAS:
1. Si el mandato es BULLISH: SOLO busca patrones de entrada LONG. Ignora cualquier señal SHORT.
2. Si el mandato es BEARISH: SOLO busca patrones de entrada SHORT. Ignora cualquier señal LONG.
3. Si el mandato es NO_TRADE: NO propongas ninguna operación (devuelve direccion vacía).
4. Score mínimo interno: 75/100.
5. Duración mínima: 5 minutos (anti quick-strike).
6. R:R mínimo: 1:1.5.

Responde SOLO JSON:
{
  "activo": "...",
  "direccion": "LONG|SHORT|NONE",
  "entrada": número,
  "stop_loss": número,
  "take_profit": número,
  "probabilidad_estimada": 0-100,
  "duracion_estimada_min": número,
  "patron": "...",
  "razon": "máx 40 palabras",
  "score_interno": 0-100
}"""


def run(activo: str, datos: str, profit_snapshot: dict = None) -> dict:
    system, variant = get_prompt("technical", activo)
    if not system:
        system = SYSTEM
    user = f"Activo: {activo}\nDatos:\n{datos}"
    if profit_snapshot:
        from context_builder import build_profit_context
        user += "\n\n" + build_profit_context(profit_snapshot)
    out = ask_json(system, user)
    out["_variant"] = variant
    return out
