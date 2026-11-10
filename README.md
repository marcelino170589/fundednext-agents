# FundedNext AI Trading System

Sistema multi-agente de análisis y señalización para trading en forex, índices y commodities. Combina 6 agentes de IA, 10 estrategias técnicas (9 validadas + Trullás), análisis fundamental en tiempo real y gestión de riesgo para cuentas de prop firms (FundedNext FNL:004).

> **Modo de uso**: el sistema **no ejecuta órdenes**. Genera señales, las valida con 9 capas de defensa y las envía a un dashboard local para que el trader las ejecute manualmente.

---

## 🏛️ Arquitectura
┌─────────────────────────────────────────────────────────────┐
│ MT5 (Windows) — OrchestratorEA.mq5 │
│ • Publica D1/H4/H1/M15/M5 de 60 instrumentos por ZMQ │
│ • Heartbeat + estado de cuenta │
│ • NO ejecuta órdenes (modo manual) │
└──────────────────────────┬──────────────────────────────────┘
│ ZMQ
▼
┌─────────────────────────────────────────────────────────────┐
│ Orquestador Python (WSL/Linux) │
│ │
│ 6 Agentes: │
│ • Trader (sesgo) │
│ • Fundamental (veredicto macro vinculante) │
│ • Técnico (patrones de entrada) │
│ • Adversario (objeciones) │
│ • HTF Pullback (estructura H1/H4) │
│ • Cazador de Oportunidades (60 instrumentos) │
│ │
│ 10 Estrategias: │
│ • Fozzy (RSI8 + EMA8) │
│ • Turtle (Donchian 20/10) │
│ • Larry Williams (%R + MA10) │
│ • Bollinger Breakout │
│ • RSI Divergence │
│ • MA Crossover (EMA20/EMA50) │
│ • MACD Signal │
│ • Order Flow │
│ • MTF Alignment (H4/H1/M15/M5) │
│ • Trullás (MACD triple divergencia) │
│ │
│ 9 Capas de defensa en el consenso + filtro de correlación │
└──────────────────────────┬──────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ Dashboard Local (FastAPI + WebSocket) │
│ • http://localhost:8000 │
│ • Alertas con sonido y notificaciones del navegador │
│ • Journal SQLite con auditoría completa │
└─────────────────────────────────────────────────────────────┘

text

---

## 🧠 Stack Tecnológico

| Componente | Tecnología |
|---|---|
| **LLM** | DeepSeek V4 (vía API compatible con OpenAI) |
| **Backend** | Python 3.10+, FastAPI, uvicorn |
| **Comunicación** | ZeroMQ (PUB/SUB), WebSocket |
| **Base de datos** | SQLite (WAL mode) |
| **Frontend** | HTML + JavaScript + Chart.js |
| **EA MT5** | MQL5 + mql-zmq |
| **Fuentes fundamentales** | ForexFactory, TradingView (tail-fin), Google News, fxnewsbias |

---

## 📊 Instrumentos Soportados

- **Forex majors (7)**: EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, NZDUSD, USDCAD
- **Forex crosses (35)**: EURGBP, EURJPY, GBPJPY, AUDJPY, etc.
- **Metales (3)**: XAUUSD, XAGUSD, XPTUSD
- **Petróleo (2)**: UKOUSD, USOUSD
- **Índices (13)**: SPX500, NDX100, US30, GER30, UK100, JP225, etc.

**Total**: 60 instrumentos escaneados cada ciclo.

---

## 🛡️ Gestión de Riesgo (FNL:004)

| Regla | Valor |
|---|---|
| Trailing drawdown | $2,000 (4%) |
| Consistency rule | 20% perpetua |
| Riesgo por trade | 0.20% ($100) |
| Riesgo abierto máximo | 0.50% ($250) |
| Objetivo diario | $100 |
| Tope duro diario | $150 |
| Filtro noticias | ±15 min |
| Modo | Manual (sin ejecución automática) |

---

## 🚀 Instalación

### Requisitos
- Ubuntu 22.04+ / WSL2
- Python 3.10+
- MetaTrader 5 (Windows, con mql-zmq)
- Cuenta DeepSeek con saldo

### Pasos

```bash
# 1. Clonar
git clone https://github.com/marcelino170589/fundednext-agents.git
cd fundednext-agents

# 2. Entorno virtual
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp setup.env .env
nano .env  # Editar con tu API key de DeepSeek

# 4. Inicializar DB
python -c "import journal; journal.init_db()"

# 5. Arrancar servicios
./start_all.sh

# 6. Dashboard
# Abrir http://localhost:8000

Configurar MT5 (Windows)
Copiar MQL5/OrchestratorEA.mq5 a MT5/MQL5/Experts/

Instalar mql-zmq en MT5/MQL5/Include/

Compilar el EA (F7)

Adjuntar a XAUUSD M15 con ZMQ_PYTHON_HOST = IP de WSL

Activar "Allow DLL imports" y "Algo Trading"

📈 Estrategias Validadas (Backtest)
Estrategia	Par	Profit Factor	Max DD
Turtle S2 (55/20)	XAUUSD	3.06	6.12R
Larry Williams	XAUUSD	2.59	5.34R
Turtle S1 (20/10)	USDJPY	1.47	7.37R
Fozzy + MA10	XAUUSD	1.39	8.79R
Fozzy + MA10	USDJPY	1.32	8.30R
## 🖥️ Dashboard v2 (nuevo)

El dashboard nuevo se sirve en `http://localhost:8000/` y el anterior queda en
`http://localhost:8000/legacy`.

Vistas: Resumen, Noticias, Oportunidades, Journal, Mercado y Sistema.
Incluye calendario económico con cuenta atrás, titulares con relevancia y
sentimiento heurístico, estado/latencia de cada fuente de noticias, salud del
EA, journal con drill-down de los agentes, velas CSV, backtests, logs y
exportación CSV. No usa CDN ni frameworks: HTML + CSS + JS vanilla.

Endpoints principales: `/api/bootstrap`, `/api/news`, `/api/health`,
`/api/symbols`, `/api/market/{symbol}`, `/api/decisions/{id}`,
`/api/journal/summary`, `/api/logs`, `/api/export/*.csv` y `/ws`.

### Flujo de noticias

`news_feed.py` es ahora el único servicio: ForexFactory JSON + Google News RSS
(+ Finnhub opcional), normalización UTC, caché memoria/disco, deduplicación,
score de relevancia, sentimiento `lexicon-v1`, ventana de bloqueo ±15 min y
telemetría de fuentes. `calendar_client.py` y `news_feed_temp.py` son
adaptadores de compatibilidad.

Ver `ANALISIS.md` para la auditoría completa, problemas encontrados y mejoras.
Ver `docs/MOVIL_Y_MONETIZACION.md` para PWA, APK, licencias y modelo de negocio.

### Telegram

El notifier envía el **detalle completo** de señales y oportunidades, divide
mensajes largos en partes (límite 4096), reintenta y deduplica. Se configura en
`.env`:

```env
TELEGRAM_BOT_TOKEN="..."
TELEGRAM_CHAT_ID="..."
TELEGRAM_ENABLED=true
TELEGRAM_MIN_SEVERITY=INFO
TELEGRAM_RATE_LIMIT_SECONDS=1.5
```

Prueba desde la API:

```bash
curl -X POST http://127.0.0.1:8000/api/telegram/test
curl http://127.0.0.1:8000/api/telegram/status
```

### PWA / móvil

El dashboard incluye `manifest.webmanifest`, service worker e iconos. Se puede
instalar desde el navegador (requiere HTTPS o localhost). Para APK, ver
`docs/MOVIL_Y_MONETIZACION.md`.

### Estado del EA y de la API

La tarjeta **API** ya no se degrada porque el EA esté desconectado: la API tiene
su propio estado (`/api/health` → `api.status`). El estado global (`status`) y
sus causas (`status_reasons`) se muestran en **Sistema**.

El EA se considera conectado cuando llega un heartbeat por ZMQ 5556 en los
últimos 120 s. `ea_monitor.py` escucha ese puerto desde la API, así que el
dashboard puede ver el EA aunque el orquestador esté reiniciándose. Se puede
desactivar con `EA_MONITOR_ENABLED=false`.

Si aparece **“EA sin heartbeat”**:

```bash
# 1. Ver si el EA está publicando en el puerto 5556
ss -lunp | grep 5556       # en Windows/MT5 no aplica; revisa el firewall
# 2. Comprobar la IP configurada
grep ZMQ_PC_IP .env
# 3. Ver el estado del monitor en /api/health
curl http://127.0.0.1:8000/api/health
```

En el EA, `ZMQ_PYTHON_HOST` debe apuntar a la IP de la máquina Python y el
puerto de estado debe ser 5556. Si el orquestador está detenido, el monitor de
la API puede mantener el heartbeat igualmente.

⚠️ Advertencias
No es una máquina de hacer dinero. Es una herramienta de análisis y filtrado.

Backtest antes de operar en vivo. Los resultados pasados no garantizan resultados futuros.

Cumple las reglas de FundedNext. El sistema está diseñado para no violar trailing DD, consistency ni riesgo abierto.

El orquestador no publica señales al EA: el trader ejecuta manualmente. El EA
`MQL5/OrchestratorEA.mq5` conserva una ruta de ejecución (`ProcessSignal` →
`PositionOpen`) que debe revisarse o desactivarse si se quiere garantizar el
modo manual.

📄 Licencia
MIT License — uso libre con atribución.
