# news_feed_temp.py
"""
Módulo legado.

En la versión anterior devolvía "titulares no disponibles" y usaba biquote
(10 s de timeout). Ahora es un shim sobre news_feed para que cualquier import
antiguo siga funcionando y reciba el contexto completo.
"""
from news_feed import (  # noqa: F401
    build_fundamental_context,
    get_calendario,
    get_eventos_hoy,
    get_headlines,
    get_sentiment,
    get_sentimiento,
    get_snapshot,
    get_titulares,
    ventana_bloqueada,
)
