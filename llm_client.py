# llm_client.py
"""
Cliente LLM compatible con la API anterior.

La implementación real vive en `llm_router.py`: soporta varios proveedores
OpenAI-compatible, varias claves por proveedor, prioridad, fallback, cooldown
y parsing robusto de JSON. Los agentes siguen llamando a `ask_json`.
"""
import logging

from llm_router import get_router, get_status, reload_router

log = logging.getLogger("llm")


def ask_json(system_prompt: str, user_prompt: str, max_retries: int = 3) -> dict:
    """Pide una respuesta JSON al primer proveedor sano de la cadena."""
    return get_router().ask_json(system_prompt, user_prompt, max_retries=max_retries)


def status() -> dict:
    return get_status()


def reload() -> dict:
    return reload_router()
