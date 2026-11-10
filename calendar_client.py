# calendar_client.py
"""
Adaptador de compatibilidad para el calendario económico.

Históricamente este módulo usaba biquote (timeout de 10 s y sin caché de
disco). Ahora delega en news_feed, que tiene una sola ruta de normalización
UTC, caché y telemetría. Se mantiene la API pública para no romper imports.
"""
import logging

from news_feed import (
    divisas_del_symbol,
    get_calendar,
    get_eventos_hoy as _get_eventos_hoy,
    ventana_bloqueada as _ventana_bloqueada,
)

log = logging.getLogger("calendar")


def get_eventos_hoy(divisas: list[str] | None = None) -> list[dict]:
    """Eventos de alto impacto de las próximas 48 h."""
    return _get_eventos_hoy(divisas)


def get_calendario(activo: str, days: int = 2) -> list[dict]:
    return get_calendar(days=days, include_medium=False,
                        currencies=divisas_del_symbol(activo))


def ventana_bloqueada(symbol: str) -> tuple[bool, str]:
    """(bloqueado, motivo) para la ventana configurada en config.py."""
    return _ventana_bloqueada(symbol)


def _divisas(symbol: str) -> set[str]:
    """Alias legado."""
    return divisas_del_symbol(symbol)


def _divisas_del_symbol(symbol: str) -> set[str]:
    return divisas_del_symbol(symbol)
