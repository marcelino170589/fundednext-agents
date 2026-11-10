# agents/agent_fundamental.py
"""
Agente Fundamental — El Capitán.
Su veredicto es VINCULANTE: BULLISH, BEARISH, NEUTRAL o NO_TRADE.
Si NO hay datos (calendario vacío, noticias caídas), devuelve NEUTRAL
(no bloquea; el técnico decide).
"""
from llm_client import ask_json
from prompt_rotator import get_prompt

SYSTEM = """Eres el Jefe de Análisis Macro de una firma de trading profesional.
Tu decisión es VINCULANTE. El analista técnico NO puede operar en contra de tu veredicto.

Recibirás: titulares recientes, sentimiento de divisas, noticias del calendario.

REGLAS ESTRICTAS:
1. Determina el SESGO MACRO del activo: BULLISH, BEARISH, NEUTRAL o NO_TRADE.
2. Si hay noticia de alto impacto en ±15 minutos, veredicto = NO_TRADE.
3. Si los titulares y el sentimiento se contradicen, prioriza las noticias de mayor impacto.
4. REGLA CRÍTICA: Si NO hay datos de noticias (titulares vacíos, calendario no disponible,
   módulo de noticias caído), devuelve NEUTRAL. NO bloquees la operación.
   El técnico decidirá con su análisis. Es MEJOR dejar operar al técnico
   que bloquear todo por falta de datos.
5. Solo devuelve NO_TRADE si hay una razón CONCRETA (noticia de alto impacto
   confirmada o conflicto macro grave). Si solo es "no tengo datos", NEUTRAL.
6. Si el sentimiento de divisas es claro (score >60 o <40), úsalo como sesgo.

Responde SOLO JSON:
{
  "activo": "...",
  "veredicto": "BULLISH|BEARISH|NEUTRAL|NO_TRADE",
  "confianza": 0-100,
  "razon": "máx 50 palabras",
  "bloqueado_por_noticia": true|false,
  "catalizador_principal": "máx 20 palabras"
}"""


def run(activo: str, contexto: str) -> dict:
    system, variant = get_prompt("fundamental", activo)
    if not system:
        system = SYSTEM
    user = f"Activo: {activo}\n\n{contexto}"
    out = ask_json(system, user)
    out["_variant"] = variant

    # Normalizar veredicto
    veredicto = str(out.get("veredicto", "NEUTRAL")).upper()
    if veredicto not in ("BULLISH", "BEARISH", "NEUTRAL", "NO_TRADE"):
        veredicto = "NEUTRAL"

    # Si el LLM dice NO_TRADE pero la razón es "sin datos", convertir a NEUTRAL
    razon = out.get("razon", "").lower()
    if veredicto == "NO_TRADE":
        palabras_sin_datos = [
            "sin datos", "no disponible", "caído", "caido", "vacío", "vacio",
            "sin calendario", "sin titulares", "no hay datos",
            "sin información", "sin informacion", "no se pudo",
            "no disponible", "módulo temporal caído", "modulo temporal caido",
        ]
        if any(p in razon for p in palabras_sin_datos):
            veredicto = "NEUTRAL"

    # Firewall de datos: un flag de "bloqueado_por_noticia" solo es válido
    # si el veredicto es realmente NO_TRADE. Si el LLM dijo NEUTRAL/BULLISH/
    # BEARISH, el flag se limpia para que el orquestador no bloquee por error.
    if veredicto != "NO_TRADE":
        out["bloqueado_por_noticia"] = False
    elif any(p in razon for p in palabras_sin_datos):
        out["bloqueado_por_noticia"] = False

    out["veredicto"] = veredicto
    return out
