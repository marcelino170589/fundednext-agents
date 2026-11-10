# Análisis del proyecto FNL:004 y del flujo de noticias

> Documento de auditoría técnica y de producto. Complementa al `README.md`.
> Fecha del análisis: 2026-11-09/10 (UTC). No es asesoría financiera.

---

## 1. Resumen ejecutivo

`fundednext_agents` es un sistema local de **análisis y señalización manual** para una cuenta FundedNext FNL:004 de 50 000 USD. No es un bot de ejecución: el orquestador genera señales y las publica en un dashboard y en SQLite; el trader decide y ejecuta en MT5.

Componentes reales:

| Capa | Implementación |
|---|---|
| Datos de mercado | EA `MQL5/OrchestratorEA.mq5` publica D1/H4/H1/M15/M5 por ZMQ. |
| Orquestación | `orchestrator.py`: ciclo cada 15 min sobre 4 símbolos principales + cazador de 60 instrumentos. |
| Agentes | Trader, fundamental, técnico, adversario, HTF y cazador (`agents/`). |
| Estrategias | 10 estrategias (incluye Trullás) + HTF Pullback + MTF (`strategies/`). |
| Consenso | `consensus_v2.py`: 9 capas de veto/score. |
| Riesgo | `fundednext_rules.py`, `profit_tracker.py`, `state_manager.py`. |
| Persistencia | `journal.py` sobre SQLite (`data/journal.db`, WAL). |
| Noticias | `news_feed.py` (nuevo servicio unificado). |
| Web | `api_server.py` (FastAPI + WebSocket) + `static/` (dashboard nuevo y legacy). |

Estado observado en los logs y la base de datos:

- El EA estaba conectado el 2026-11-09 (heartbeat y equity ~51 503 USD) y ahora está offline en esta copia.
- `data/journal.db`: 53 decisiones, 0 señales, 0 trades y 75 snapshots de equity. Es decir, **el sistema todavía no ha emitido una señal válida**; la mayoría de los vetos son por score (<80), adversario y falta de datos.
- El ciclo del orquestador tardaba ~4 minutos: 4 símbolos × llamadas LLM + 60 instrumentos del cazador. Parte del tiempo se iba en noticias y en el escaneo secuencial.
- El histórico CSV está desactualizado (última vela XAUUSD H1: 2026-11-06), por lo que la web lo marca como `stale` y no lo presenta como precio en vivo.

### Hallazgo crítico de seguridad/operación

El `README.md` afirma que el EA **no ejecuta órdenes**, pero `MQL5/OrchestratorEA.mq5` sí tiene una ruta de ejecución (`ProcessSignal` → `CTrade::PositionOpen`). Hoy el orquestador no publica señales (modo manual), así que la ruta está inactiva, pero **cualquier proceso que publique en el puerto ZMQ 5555 podría abrir órdenes**. Recomendación: añadir un flag `EXECUTION_ENABLED=false` en el EA y desactivar `ProcessSignal`, o separar el EA de datos del EA de ejecución. No se modificó el `.mq5` en esta iteración.

---

## 2. Arquitectura y flujo real

```
MT5 (Windows)                         Linux / WSL
┌────────────────────┐   ZMQ 5556    ┌──────────────────────────────┐
│ OrchestratorEA.mq5 │ ────────────► │ state_manager / journal      │
│ • OHLC 5557        │   ZMQ 5557    │                              │
│ • heartbeat/estado │ ────────────► │ orchestrator.py              │
│ • (ruta de órdenes)│   ZMQ 5555    │   ├─ news_feed               │
└────────────────────┘ ◄──────────── │   ├─ 6 agentes + estrategias │
                                     │   ├─ consenso 9 capas        │
                                     │   └─ risk / profit tracker   │
                                     └──────────────┬───────────────┘
                                                    │ SQLite + WebSocket
                                                    ▼
                                     FastAPI :8000 + dashboard web
```

### Pipeline por símbolo (`orchestrator.procesar_symbol`)

1. Sesión y límites: horario, objetivo diario, consistency <20 %.
2. **Noticias**: ventana de bloqueo ±15 min (nuevo chequeo explícito antes del LLM).
3. Agente fundamental: veredicto vinculante (`BULLISH/BEARISH/NEUTRAL/NO_TRADE`).
4. Agente trader (sesgo) + agente técnico (entrada/SL/TP) en paralelo.
5. Estrategias clásicas sobre D1/H4/H1/M15/M5.
6. HTF Pullback (si hay estado fresco) y adversario.
7. Consenso de 9 capas; si opera, cálculo de lotaje y validación FNL.
8. Alerta local en SQLite + señal en journal. **No se envía al EA.**
9. Cazador de oportunidades: escanea 60 instrumentos cada ciclo.

### Fortalezas

- Separación clara de responsabilidades y jerarquía fundamental → técnico → consenso.
- Reglas de riesgo conservadoras y auditables (trailing DD, consistency, riesgo abierto, tope diario).
- Journal SQLite con decisiones completas por agente, útil para post-mortem.
- Fallbacks y modo manual bien pensados.
- Backtests y catálogo de estrategias documentados.

### Debilidades detectadas

- **Noticias**: el orquestador usaba un stub sin titulares (`news_feed_temp.py`) mientras `news_feed.py` tenía la implementación rica sin usar. Tres módulos de calendario duplicados.
- **Latencia**: `biquote` con timeout de 10 s y sin caché de disco bloqueaba el ciclo.
- **Zona horaria**: se hacía `datetime.fromisoformat(...).replace(tzinfo=None)`, descartando el offset; los eventos de ForexFactory se corrían varias horas.
- **Veto por falta de datos**: el agente limpiaba `veredicto` a `NEUTRAL` pero no `bloqueado_por_noticia`; el orquestador vetaba igualmente. Los logs muestran “Macro: NEUTRAL” seguido de “VETO FUNDAMENTAL”.
- **Mapa de índices**: `GER30→DE`, `UK100→GB`, etc. no coincide con los códigos de divisa de ForexFactory (`EUR`, `GBP`). Esos activos nunca recibían noticias.
- **Sin telemetría**: los fallos de fuentes solo quedaban en `debug`; ni el dashboard ni el trader sabían si el calendario estaba caído.
- **Score ausente en vetos**: los vetos por capa 4/5/6/7/9 no guardaban `score`, dejando el journal incompleto.
- **Cazador secuencial**: 60 símbolos × timeout de 1 s; en la práctica cargó 24 instrumentos y tardó ~60 s.
- **Datos CSV**: históricos congelados; no hay validación de antigüedad en la UI anterior.
- **Seguridad**: `.env` y `setup.env` contienen credenciales reales en disco; `logs/*.out` están trackeados en git. No hay autenticación en la API (aunque escucha en 127.0.0.1).
- **README desactualizado** en varios puntos (ejecución del EA, modelo, número de agentes).

---

## 3. Flujo de noticias: antes y después

### Antes (resumen del código original)

```
orchestrator.procesar_symbol
  └─ news_feed_temp.build_fundamental_context(symbol)
       └─ biquote.calendar(importance="high", countries=...)
            ├─ timeout 10 s, sin caché de disco
            ├─ solo 5 eventos, sin titulares
            └─ "Titulares no disponibles (módulo temporal)."
  └─ agent_fundamental.run(...)
       └─ LLM decide con datos vacíos
  └─ si veredicto == NO_TRADE or bloqueado_por_noticia → veto
```

Problemas concretos:

1. El módulo rico `news_feed.py` (ForexFactory JSON, tail-fin, pyfinews, Google News, Finnhub, fxnewsbias) **no se importaba**.
2. `calendar_client.py` duplicaba la lógica con `biquote`; el cazador lo usaba para el veto.
3. `news_feed_temp.py` devolvía “sin titulares” siempre.
4. La caché del calendario en `news_feed.py` no distinguía el conjunto de divisas solicitado.
5. `ventana_bloqueada` comparaba `datetime` naive contra UTC sin convertir el offset.
6. La relevancia de titulares era una lista de palabras; si dejaba <2 titulares, devolvía los originales (ruido).
7. El sentimiento dependía de `fxnewsbias`/`tradekix` (API keys) y devolvía un texto vacío si no había claves.
8. No había forma de saber desde la web si una fuente estaba caída, cuánto tardaba o cuándo fue la última OK.

### Después (implementado)

`news_feed.py` es ahora el **único servicio de noticias**:

```
ForexFactory JSON ─┐
Google News RSS  ──┼─► normalización UTC ─► caché memoria+disco ─► relevancia/dedupe
Finnhub (opcional)┘                            │
                                               ├─► sentimiento lexicon-v1
                                               ├─► ventana ±15 min
                                               └─► contexto para el LLM
```

Mejoras aplicadas:

| # | Mejora | Dónde |
|---|---|---|
| 1 | Un solo módulo y API compatible (`get_eventos_hoy`, `get_titulares`, `get_sentimiento`, `ventana_bloqueada`, `build_fundamental_context`). | `news_feed.py` |
| 2 | Normalización UTC real con `astimezone(UTC)`. | `_parse_dt` |
| 3 | Caché en memoria + `data/news_cache.json`, TTL y backoff de 60 s tras fallo. | `refresh_calendar`, `get_headlines` |
| 4 | Timeout de 8 s configurable (`NEWS_HTTP_TIMEOUT`). | constantes |
| 5 | Titulares reales por Google News RSS (`requests` + `feedparser`) y Finnhub opcional. | `_google_news_items`, `_finnhub_items` |
| 6 | Score de relevancia por activo, deduplicación por similitud y filtro de ruido. | `_relevance`, `_dedupe`, `_rank_headlines` |
| 7 | Sentimiento heurístico etiquetado (`lexicon-v1`) con divisas, metales, índices y petróleo. | `_headline_impact`, `get_sentiment` |
| 8 | Veto explícito antes del LLM y flag normalizado. | `orchestrator`, `agent_fundamental` |
| 9 | Mapa de índices corregido a divisas de ForexFactory. | `INDEX_CURRENCIES` |
| 10 | Telemetría: estado, latencia, última OK, error y conteo por fuente. | `_health`, `get_health` |
| 11 | `calendar_client.py` y `news_feed_temp.py` pasan a ser adaptadores del servicio. | ambos |
| 12 | Cazador usa el mismo contexto y la misma ventana de noticias. | `agent_opportunity_hunter` |
| 13 | Web muestra calendario, titulares, sentimiento, pipeline y salud de fuentes. | `static/app.js` |

### Resultados medidos en esta máquina

- ForexFactory JSON: **~0,4 s**, 11 eventos high/medium esta semana (8 en las próximas 72 h).
- Google News RSS: **~1,1 s**, 40 entradas, 12 relevantes para XAUUSD tras filtro.
- `get_snapshot` en caliente: **< 50 ms**; primer `build_fundamental_context` completo: ~2 s.
- La ventana de CPI de las 08:30-05:00 ahora se lee como **13:30 UTC** (antes 08:30 UTC).
- `biquote` ya no se invoca en la ruta principal; se eliminó el bloqueo de 10 s.

### Recomendaciones pendientes (no implementadas)

1. **Calendario de la próxima semana**: ForexFactory solo publica `thisweek` (el `nextweek` devuelve 404); añadir otra fuente o scrapear el detalle para cubrir el fin de semana.
2. **Sentimiento con API de pago** (fxnewsbias/tradekix) como fuente opcional jerárquica, manteniendo el heurístico como fallback.
3. **Histórico de noticias** en SQLite para estudiar reacción precio/evento y calibrar la ventana (15 min es arbitrario).
4. **Telegram** ya envía señales/oportunidades completas con cola, chunks, reintentos y deduplicación; el siguiente paso es Web Push/FCM para la app móvil.
5. **Deduplicación semántica** con embeddings o similitud de titulares más robusta.
6. **Tests automáticos** de zona horaria, filtros y fuentes con fixtures; hoy la verificación es manual.
7. **Webhooks/healthchecks** para el orquestador y el EA; el dashboard ya muestra la edad del log, pero no alerta si se queda viejo.
8. **Rotar credenciales** de `.env`/`setup.env` y dejar de trackear `logs/*.out` en git.
9. **Revisar el EA**: desactivar la ruta de ejecución si el modo es manual, o documentarla con claridad.

---

## 4. Dashboard web nuevo

Se conserva el dashboard anterior en `/legacy` (`static/legacy.html`) y se sirve el nuevo en `/`:

- `static/index.html` + `static/app.css` + `static/app.js` (vanilla JS, sin CDN).
- `api_server.py` amplía la API y mantiene compatibilidad con los endpoints anteriores.

### Vistas

| Vista | Contenido |
|---|---|
| **Resumen** | Equity, P&L, 4 gauges de riesgo, objetivo, retiro, curva, próximos eventos, oportunidades, salud, decisiones y alertas. |
| **Noticias** | Calendario por día, filtros, cuenta atrás, titulares con relevancia/sentimiento, panel de sentimiento, pipeline de 8 pasos y salud de fuentes. |
| **Oportunidades** | Tarjetas con entrada/SL/TP/lote/R:R, filtros, copiar plan, detalle JSON, señales y alertas del cazador. |
| **Journal** | KPIs, equity, vetos por capa, decisiones con drill-down de los 7 agentes, trades, alertas y exportación CSV. |
| **Mercado** | Velas CSV, resumen (cambio, rango, ATR, SMA20/50), tablas, backtests y catálogo de estrategias. |
| **Sistema** | Salud, configuración segura, logs, arquitectura y auditoría del flujo de noticias. |

### API nueva

| Endpoint | Uso |
|---|---|
| `GET /api/bootstrap?symbol=XAUUSD` | Carga inicial completa y compacta. |
| `GET /api/news?symbol=XAUUSD&refresh=0` | Snapshot de noticias (calendario, titulares, sentimiento, veto, salud). |
| `POST /api/news/refresh?symbol=XAUUSD` | Fuerza actualización. |
| `GET /api/health` | EA, noticias, DB, uptime, logs. |
| `GET /api/symbols` | 60 instrumentos con timeframes disponibles. |
| `GET /api/market/{symbol}?tf=H1` | Velas CSV + resumen técnico + staleness. |
| `GET /api/backtests` | Resultados de `data/backtest_*.json` y `grid_*.json`. |
| `GET /api/strategies` | Catálogo y validaciones. |
| `GET /api/decisions/{id}` | Decisión con agentes parseados. |
| `GET /api/journal/summary?days=30` | Agregados por capa/símbolo/trades. |
| `GET /api/logs?name=orchestrator` | Logs permitidos. |
| `GET /api/export/*.csv` | Exportación de decisiones, alertas y trades. |
| `WS /ws` | Snapshot ligero cada 2 s. |

### Ejecución

```bash
cd /root/fundednext_agents
source venv/bin/activate
python -m py_compile api_server.py news_feed.py orchestrator.py
uvicorn api_server:app --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000
```

El servidor de esta sesión se dejó corriendo en `http://127.0.0.1:8000` como job gestionado.

---

## 5. Verificación realizada

- `python -m py_compile` de todos los módulos modificados.
- `FastAPI TestClient` sobre 20+ endpoints: estado, noticias, mercado, journal, logs, exportaciones, bootstrap.
- `node --check static/app.js`.
- Prueba de render con `jsdom` (sin navegador real):
  - 4 gauges, 4 KPIs, 4 próximos eventos, 6 filas de salud.
  - Noticias: 8 eventos, 12 titulares, 8 pasos de pipeline, 4 filas de salud.
  - Oportunidades: 9 tarjetas, 53 decisiones, 15 velas, 3 backtests, catálogo de estrategias (incluye Trullás), 24 filas de configuración.
  - Interacciones: modal de decisión con 7 tarjetas de agentes, drawer de 12 alertas, modal de oportunidad, cambio H1→M15, carga de logs.
  - Consola: 0 errores.
- Comprobación de zona horaria: `CPI 13:30 UTC` para el evento de las 08:30-05:00.

Limitaciones de la verificación:

- No hay navegador gráfico en el entorno; el layout se validó por DOM, no por píxeles.
- El EA/MT5 estaba offline, por lo que no se probó el flujo ZMQ en vivo.
- No se llamó al LLM en esta iteración (coste/credenciales); se validó el contexto y la normalización.

---

## 6. Archivos modificados/creados

| Archivo | Cambio |
|---|---|
| `news_feed.py` | Reescritura completa como servicio unificado. |
| `calendar_client.py` | Adaptador a `news_feed`. |
| `news_feed_temp.py` | Shim de compatibilidad. |
| `orchestrator.py` | Importa `news_feed`; veto de noticias antes del LLM. |
| `agents/agent_fundamental.py` | Normaliza `bloqueado_por_noticia`. |
| `agents/agent_opportunity_hunter.py` | Usa `news_feed`. |
| `consensus_v2.py` | Guarda `score` en vetos. |
| `strategies/trullas.py` | MACD triple divergencia, RSI, volumen y Fibonacci (aproximación pública). |
| `docs/ESTRATEGIA_TRULLAS.md` | Reglas, fuentes, límites y validación pendiente. |
| `journal.py` | Helpers de decisión, señales, resumen y conteos. |
| `notifier.py` | Telegram completo: cola, chunks, reintentos, rate-limit y deduplicación. |
| `ea_monitor.py` | Monitor ZMQ independiente para que el dashboard vea el EA aunque el orquestador esté detenido. |
| `static/manifest.webmanifest`, `static/sw.js`, `static/icon-*.png` | PWA instalable. |
| `docs/MOVIL_Y_MONETIZACION.md` | APK, PWA, licencias y monetización. |
| `api_server.py` | API v2 y estáticos. |
| `static/index.html`, `app.css`, `app.js`, `favicon.svg` | Dashboard nuevo. |
| `static/legacy.html` | Dashboard anterior conservado. |
| `ANALISIS.md` | Este documento. |
