# api_server.py
"""
API + WebSocket del dashboard FNL:004.

Diseño:
  - Los endpoints REST son de solo lectura (no ejecutan órdenes).
  - El WebSocket envía un snapshot ligero cada 2 s; las vistas pesadas
    (noticias, mercado, journal) se piden por REST.
  - Si MT5/EA no está conectado, la API sigue funcionando con el estado,
    el journal y los datos históricos en CSV.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import journal
import news_feed
import notifier
from state_manager import load as load_state, ea_vivo, ultimo_heartbeat

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
START_TS = time.time()
APP_VERSION = "2.0.0"

app = FastAPI(title="FNL:004 Professional API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class Manager:
    def __init__(self):
        self.clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)


mgr = Manager()


# ═══════════════════════════════════════════════════════════════
# Arranque
# ═══════════════════════════════════════════════════════════════

@app.on_event("startup")
async def _startup():
    journal.init_db()
    # Calienta calendario/titulares en segundo plano; la API responde ya.
    news_feed.warm_up(background=True)


# ═══════════════════════════════════════════════════════════════
# Páginas
# ═══════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def root():
    path = STATIC_DIR / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>Dashboard no encontrado</h1>", status_code=500)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/legacy", response_class=HTMLResponse)
async def legacy():
    path = STATIC_DIR / "legacy.html"
    if not path.exists():
        return HTMLResponse("<h1>Dashboard legacy no encontrado</h1>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/favicon.svg")
async def favicon():
    path = STATIC_DIR / "favicon.svg"
    if path.exists():
        return Response(path.read_bytes(), media_type="image/svg+xml")
    raise HTTPException(404, "favicon no encontrado")


@app.get("/sw.js")
async def service_worker():
    path = STATIC_DIR / "sw.js"
    if not path.exists():
        raise HTTPException(404, "service worker no encontrado")
    return Response(
        path.read_bytes(), media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _safe_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _file_meta(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "mtime": None, "age_sec": None, "size": 0}
    stat = path.stat()
    return {
        "exists": True,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "age_sec": max(0, int(time.time() - stat.st_mtime)),
        "size": stat.st_size,
    }


def _public_state() -> dict:
    st = load_state()
    st["ea_alive"] = ea_vivo(120)
    st["last_heartbeat"] = ultimo_heartbeat()
    return st


def _health_payload() -> dict:
    state = _public_state()
    heartbeat = state.get("last_heartbeat") or {}
    news = news_feed.get_health()
    calendar_status = news["sources"].get("calendar", {}).get("status")
    news_ok = calendar_status == "ok"
    ea_ok = bool(state.get("ea_alive"))
    status = "ok" if (ea_ok and news_ok) else "degraded"
    return {
        "status": status,
        "version": APP_VERSION,
        "now_utc": datetime.now(timezone.utc).isoformat(),
        "uptime_sec": int(time.time() - START_TS),
        "ea": {
            "alive": ea_ok,
            "heartbeat_age_sec": (
                max(0, int(time.time() - float(heartbeat.get("ts", 0))))
                if heartbeat.get("ts") else None
            ),
            "account": heartbeat.get("account"),
            "equity": state.get("equity"),
            "balance": state.get("balance"),
        },
        "news": news,
        "telegram": notifier.get_status(),
        "db": journal.get_counts(),
        "files": {
            "orchestrator_log": _file_meta(LOGS_DIR / "orchestrator.out"),
            "htf_log": _file_meta(LOGS_DIR / "htf.out"),
            "api_log": _file_meta(LOGS_DIR / "api.out"),
            "state": _file_meta(LOGS_DIR / "state.json"),
            "journal": _file_meta(DATA_DIR / "journal.db"),
            "htf_state": _file_meta(DATA_DIR / "htf_state.json"),
        },
    }


def _safe_config() -> dict:
    from config import (
        INITIAL_BALANCE, MAX_LOSS_USD, RISK_PER_TRADE, MAX_LOT,
        OPERATIONAL_DAILY_LOSS_LIMIT, OPERATIONAL_MAX_RISK_OPEN,
        MAX_DAILY_PROFIT_USD, HARD_DAILY_CAP, NEWS_BLACKOUT_MIN,
        MIN_SCORE_CONSENSUS, MIN_CONFLUENCIA, SCORE_MINIMO,
        SESSION_ENABLED, SESSION_START_UTC, SESSION_END_UTC,
        NO_OPERATE_FRIDAY_AFTER_UTC, SYMBOLS, FILTRAR_CORRELACION,
        DILUTION_ENABLED, CONSISTENCY_LIMIT,
    )
    return {
        "mode": "manual",
        "account": "FNL:004 Instant 50K",
        "initial_balance": INITIAL_BALANCE,
        "max_loss_usd": MAX_LOSS_USD,
        "risk_per_trade_pct": RISK_PER_TRADE * 100,
        "max_lot": MAX_LOT,
        "daily_loss_limit_pct": OPERATIONAL_DAILY_LOSS_LIMIT * 100,
        "max_open_risk_pct": OPERATIONAL_MAX_RISK_OPEN * 100,
        "daily_target_usd": MAX_DAILY_PROFIT_USD,
        "hard_daily_cap_usd": HARD_DAILY_CAP,
        "news_blackout_min": NEWS_BLACKOUT_MIN,
        "min_score_consensus": MIN_SCORE_CONSENSUS,
        "min_confluencia": MIN_CONFLUENCIA,
        "score_minimo": SCORE_MINIMO,
        "consistency_limit_pct": CONSISTENCY_LIMIT * 100,
        "session": {
            "enabled": SESSION_ENABLED,
            "start_utc": SESSION_START_UTC,
            "end_utc": SESSION_END_UTC,
            "friday_cutoff_utc": NO_OPERATE_FRIDAY_AFTER_UTC,
        },
        "symbols": SYMBOLS,
        "filter_correlation": FILTRAR_CORRELACION,
        "dilution_enabled": DILUTION_ENABLED,
        "telegram_enabled": notifier.get_status()["enabled"],
        "execution": "disabled_manual_only",
    }


def _symbol_group(symbol: str) -> str:
    s = symbol.upper()
    if s.startswith(("XAU", "XAG", "XPT")):
        return "metales"
    if s in ("UKOUSD", "USOUSD"):
        return "petróleo"
    if s in ("SPX500", "NDX100", "US30", "US2000", "GER30", "UK100", "FRA40",
             "EUSTX50", "SWI20", "JP225", "HK50", "AUS200", "NTH25"):
        return "índices"
    return "forex"


def _available_timeframes(symbol: str) -> list[str]:
    found = []
    for tf in ("D1", "H4", "H1", "M15", "M5", "M1"):
        if (DATA_DIR / f"{symbol.upper()}_{tf}.csv").exists():
            found.append(tf)
    return found


# ═══════════════════════════════════════════════════════════════
# Endpoints base (compatibles con el dashboard anterior)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/state")
async def api_state():
    return _public_state()


@app.get("/api/stats/today")
async def api_stats():
    return journal.get_stats_today()


@app.get("/api/trades")
async def api_trades(limit: int = Query(100, ge=1, le=1000)):
    return journal.get_recent_trades(limit)


@app.get("/api/decisions")
async def api_decisions(limit: int = Query(50, ge=1, le=500),
                        compact: int = 0):
    rows = journal.get_recent_decisions(limit)
    if compact:
        keys = ("id", "ts", "symbol", "operar", "motivo", "capa", "score",
                "divergencia", "direction")
        rows = [{k: r.get(k) for k in keys} for r in rows]
    return rows


@app.get("/api/decisions/{decision_id}")
async def api_decision_detail(decision_id: int):
    row = journal.get_decision(decision_id)
    if not row:
        raise HTTPException(404, "Decisión no encontrada")
    return row


@app.get("/api/signals")
async def api_signals(limit: int = Query(50, ge=1, le=500)):
    return journal.get_recent_signals(limit)


@app.get("/api/equity")
async def api_equity(limit: int = Query(500, ge=1, le=2000)):
    return journal.get_equity_curve(limit)


@app.get("/api/profit")
async def api_profit():
    from profit_tracker import ProfitTracker
    return ProfitTracker.load("default").snapshot()


@app.get("/api/htf")
async def api_htf():
    data = _safe_json(DATA_DIR / "htf_state.json", {"symbols": {}})
    if not isinstance(data, dict):
        return {"symbols": {}}
    return data


@app.get("/api/alerts")
async def api_alerts(limit: int = Query(50, ge=1, le=500),
                     solo_no_leidas: bool = False):
    return journal.get_alerts(limit, solo_no_leidas)


@app.post("/api/alerts/{alert_id}/read")
async def api_alert_read(alert_id: int):
    journal.mark_alert_read(alert_id)
    return {"ok": True, "alert_id": alert_id}


@app.post("/api/alerts/read-all")
async def api_alerts_read_all():
    journal.mark_all_alerts_read()
    return {"ok": True}


@app.post("/api/alerts/clear")
async def api_alerts_clear():
    journal.clear_read_alerts()
    return {"ok": True}


@app.get("/api/alerts/count")
async def api_alerts_count():
    return {"unread": journal.get_unread_count()}


@app.get("/api/journal/summary")
async def api_journal_summary(days: int = Query(30, ge=1, le=365)):
    return journal.get_journal_summary(days)


@app.get("/api/telegram/status")
async def api_telegram_status():
    return notifier.get_status()


@app.post("/api/telegram/test")
async def api_telegram_test():
    queued = notifier.send_test_message()
    return {"queued": queued, "status": notifier.get_status()}


# ═══════════════════════════════════════════════════════════════
# Noticias
# ═══════════════════════════════════════════════════════════════

@app.get("/api/news")
async def api_news(symbol: str = "XAUUSD", refresh: int = 0,
                   days: int = Query(3, ge=1, le=7), cached: int = 0):
    symbol = re.sub(r"[^A-Za-z0-9]", "", symbol).upper() or "XAUUSD"
    if cached:
        return await asyncio.to_thread(news_feed.peek_snapshot, symbol, days)
    return await asyncio.to_thread(
        news_feed.get_snapshot, symbol,
        refresh=bool(refresh), days=days, include_medium=True,
    )


@app.post("/api/news/refresh")
async def api_news_refresh(symbol: str = "XAUUSD"):
    symbol = re.sub(r"[^A-Za-z0-9]", "", symbol).upper() or "XAUUSD"
    return await asyncio.to_thread(
        news_feed.get_snapshot, symbol, refresh=True, days=3, include_medium=True,
    )


# ═══════════════════════════════════════════════════════════════
# Salud / sistema / configuración
# ═══════════════════════════════════════════════════════════════

@app.get("/api/health")
async def api_health():
    return _health_payload()


@app.get("/api/config")
async def api_config():
    return _safe_config()


@app.get("/api/symbols")
async def api_symbols():
    from symbol_config import DEFAULT_CONFIGS
    from config import SYMBOLS as MAIN_SYMBOLS
    main = set(MAIN_SYMBOLS)
    rows = []
    for symbol, cfg in DEFAULT_CONFIGS.items():
        rows.append({
            "symbol": symbol,
            "group": _symbol_group(symbol),
            "main": symbol in main,
            "pip_size": cfg.pip_size,
            "pip_value_per_lot": cfg.pip_value_per_lot,
            "timeframes": _available_timeframes(symbol),
        })
    rows.sort(key=lambda r: (not r["main"], r["group"], r["symbol"]))
    return {"count": len(rows), "main": MAIN_SYMBOLS, "symbols": rows}


@app.get("/api/strategies")
async def api_strategies():
    return {
        "strategies": [
            {"name": "Fozzy", "timeframes": "D1/H1",
             "desc": "RSI(8) cruza EMA(8); validada en XAUUSD y USDJPY."},
            {"name": "Turtle S1/S2", "timeframes": "D1",
             "desc": "Donchian 20/10 y 55/20; ruptura de canal."},
            {"name": "Larry Williams", "timeframes": "D1",
             "desc": "%R + MA(10); reversión y confirmación de impulso."},
            {"name": "Bollinger Breakout", "timeframes": "D1/H4",
             "desc": "Ruptura de bandas con expansión de volatilidad."},
            {"name": "RSI Divergence", "timeframes": "H4/H1",
             "desc": "Divergencias precio-RSI en zonas de agotamiento."},
            {"name": "MA Crossover", "timeframes": "D1/H4",
             "desc": "Cruce EMA(20)/EMA(50) con filtro de tendencia."},
            {"name": "MACD Signal", "timeframes": "H4/H1",
             "desc": "Cruce de MACD y señal con histograma."},
            {"name": "Order Flow", "timeframes": "M15",
             "desc": "Presión compradora/vendedora y desequilibrios."},
            {"name": "MTF Alignment", "timeframes": "H4/H1/M15/M5",
             "desc": "Alineación multi-timeframe de estructura y momentum."},
            {"name": "HTF Pullback", "timeframes": "H4/H1",
             "desc": "Retroceso saludable a zona clave con vela de rechazo."},
            {"name": "Trullás · MACD triple divergencia", "timeframes": "M5/M15/H1/H4",
             "desc": "Tres pivotes con divergencia MACD, confirmación RSI/volumen y zona Fibonacci. Aproximación pública, no validada por el autor."},
        ],
        "validated": [
            {"strategy": "Turtle S2 (55/20)", "symbol": "XAUUSD",
             "profit_factor": 3.06, "max_dd_r": 6.12},
            {"strategy": "Larry Williams", "symbol": "XAUUSD",
             "profit_factor": 2.59, "max_dd_r": 5.34},
            {"strategy": "Turtle S1 (20/10)", "symbol": "USDJPY",
             "profit_factor": 1.47, "max_dd_r": 7.37},
            {"strategy": "Fozzy + MA10", "symbol": "XAUUSD",
             "profit_factor": 1.39, "max_dd_r": 8.79},
            {"strategy": "Fozzy + MA10", "symbol": "USDJPY",
             "profit_factor": 1.32, "max_dd_r": 8.30},
        ],
    }


@app.get("/api/logs")
async def api_logs(name: str = "orchestrator",
                   lines: int = Query(200, ge=20, le=1000)):
    allowed = {
        "orchestrator": "orchestrator.out",
        "orchestrator.log": "orchestrator.log",
        "htf": "htf.out",
        "api": "api.out",
    }
    filename = allowed.get(name)
    if not filename:
        raise HTTPException(400, f"log no permitido: {name}")
    path = LOGS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "log no encontrado")

    def _read():
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readlines()[-lines:]

    content = await asyncio.to_thread(_read)
    return {
        "name": name,
        "file": filename,
        "lines": [line.rstrip("\n") for line in content],
        "meta": _file_meta(path),
    }


# ═══════════════════════════════════════════════════════════════
# Mercado (CSV histórico; no requiere EA)
# ═══════════════════════════════════════════════════════════════

def _read_market_csv(symbol: str, timeframe: str, limit: int) -> dict:
    symbol = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    timeframe = timeframe.upper()
    if timeframe not in ("D1", "H4", "H1", "M15", "M5", "M1"):
        raise HTTPException(400, "timeframe inválido")
    path = DATA_DIR / f"{symbol}_{timeframe}.csv"
    if not path.exists():
        raise HTTPException(
            404, f"sin datos para {symbol} {timeframe}. "
                 f"Disponibles: {', '.join(_available_timeframes(symbol)) or 'ninguno'}"
        )

    rows: list[dict] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                rows.append({
                    "time": row.get("time", ""),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0),
                })
            except (KeyError, TypeError, ValueError):
                continue
    if not rows:
        raise HTTPException(404, "CSV vacío o mal formado")

    limit = max(20, min(int(limit), 1000))
    candles = rows[-limit:]
    history = rows[-max(limit + 60, 220):]
    closes = [c["close"] for c in history]

    def _sma(period: int):
        if len(closes) < period:
            return None
        return round(sum(closes[-period:]) / period, 6)

    atr = None
    if len(history) >= 15:
        trs = []
        for i in range(1, len(history)):
            high, low = history[i]["high"], history[i]["low"]
            prev = history[i - 1]["close"]
            trs.append(max(high - low, abs(high - prev), abs(low - prev)))
        atr = round(sum(trs[-14:]) / 14, 6)

    last = candles[-1]
    previous = candles[-2] if len(candles) > 1 else last
    change = last["close"] - previous["close"]
    change_pct = (change / previous["close"] * 100) if previous["close"] else 0.0

    last_dt = None
    try:
        last_dt = datetime.fromisoformat(last["time"]).replace(tzinfo=timezone.utc)
    except Exception:
        pass
    stale_sec = (
        max(0, int((datetime.now(timezone.utc) - last_dt).total_seconds()))
        if last_dt else None
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "csv_historico",
        "file": path.name,
        "candles": candles,
        "count": len(candles),
        "last_time": last["time"],
        "stale": bool(stale_sec is not None and stale_sec > 86400),
        "stale_sec": stale_sec,
        "summary": {
            "last": last["close"],
            "change": round(change, 6),
            "change_pct": round(change_pct, 3),
            "high": max(c["high"] for c in candles),
            "low": min(c["low"] for c in candles),
            "sma20": _sma(20),
            "sma50": _sma(50),
            "atr14": atr,
        },
        "available_timeframes": _available_timeframes(symbol),
    }


@app.get("/api/market/{symbol}")
async def api_market(symbol: str, tf: str = "H1",
                     limit: int = Query(180, ge=20, le=1000)):
    return await asyncio.to_thread(_read_market_csv, symbol, tf, limit)


@app.get("/api/backtests")
async def api_backtests():
    results = []

    def _read():
        for path in sorted(DATA_DIR.glob("backtest_*.json")):
            data = _safe_json(path, None)
            if isinstance(data, dict):
                results.append({
                    "name": path.stem.replace("backtest_", ""),
                    "file": path.name,
                    "kind": "backtest",
                    "symbol": path.stem.replace("backtest_", "").upper(),
                    "metrics": {k: data.get(k) for k in (
                        "trades", "wins", "losses", "hit_rate", "profit_factor",
                        "avg_r", "total_r", "max_dd_r")},
                    "meta": _file_meta(path),
                })
        for path in sorted(DATA_DIR.glob("grid_*.json")):
            data = _safe_json(path, None)
            if isinstance(data, dict):
                top = data.get("top") or {}
                results.append({
                    "name": path.stem.replace("grid_", "") + " (grid)",
                    "file": path.name,
                    "kind": "grid",
                    "symbol": path.stem.replace("grid_", "").upper(),
                    "best": top.get("best_pf") or {},
                    "meta": _file_meta(path),
                })
        return results

    return await asyncio.to_thread(_read)


# ═══════════════════════════════════════════════════════════════
# Exportaciones
# ═══════════════════════════════════════════════════════════════

def _csv_response(rows: list[dict], filename: str) -> Response:
    if not rows:
        rows = [{"sin_datos": ""}]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/decisions.csv")
async def export_decisions(limit: int = Query(5000, ge=1, le=20000)):
    rows = journal.get_recent_decisions(limit)
    for row in rows:
        for key in ("agent_trader", "agent_fundamental", "agent_technical",
                    "agent_adversary", "agent_htf", "agent_strategies",
                    "prompt_variants"):
            if isinstance(row.get(key), (dict, list)):
                row[key] = json.dumps(row[key], ensure_ascii=False)
    return _csv_response(rows, "fnl004_decisiones.csv")


@app.get("/api/export/alerts.csv")
async def export_alerts(limit: int = Query(5000, ge=1, le=20000)):
    rows = journal.get_alerts(limit)
    for row in rows:
        if isinstance(row.get("data"), (dict, list)):
            row["data"] = json.dumps(row["data"], ensure_ascii=False)
    return _csv_response(rows, "fnl004_alertas.csv")


@app.get("/api/export/trades.csv")
async def export_trades(limit: int = Query(5000, ge=1, le=20000)):
    return _csv_response(journal.get_recent_trades(limit), "fnl004_trades.csv")


# ═══════════════════════════════════════════════════════════════
# Bootstrap (una sola llamada para la primera carga del dashboard)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/bootstrap")
async def api_bootstrap(symbol: str = "XAUUSD"):
    symbol = re.sub(r"[^A-Za-z0-9]", "", symbol).upper() or "XAUUSD"
    news = await asyncio.to_thread(news_feed.peek_snapshot, symbol, 3)
    from profit_tracker import ProfitTracker
    compact_keys = ("id", "ts", "symbol", "operar", "motivo", "capa", "score",
                    "divergencia", "direction")
    decisions = [
        {k: row.get(k) for k in compact_keys}
        for row in journal.get_recent_decisions(30)
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": _public_state(),
        "stats": journal.get_stats_today(),
        "profit": ProfitTracker.load("default").snapshot(),
        "trades": journal.get_recent_trades(20),
        "decisions": decisions,
        "signals": journal.get_recent_signals(20),
        "equity": journal.get_equity_curve(200),
        "alerts": journal.get_alerts(30),
        "alerts_unread": journal.get_unread_count(),
        "htf": _safe_json(DATA_DIR / "htf_state.json", {"symbols": {}}),
        "news": news,
        "config": _safe_config(),
        "health": _health_payload(),
    }


# ═══════════════════════════════════════════════════════════════
# WebSocket
# ═══════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def ws_ep(ws: WebSocket):
    await mgr.connect(ws)
    try:
        while True:
            from profit_tracker import ProfitTracker
            state = _public_state()
            news = news_feed.peek_snapshot("XAUUSD", 2)
            compact_keys = ("id", "ts", "symbol", "operar", "motivo", "capa",
                            "score", "divergencia", "direction")
            decisions = [
                {k: row.get(k) for k in compact_keys}
                for row in journal.get_recent_decisions(5)
            ]
            await ws.send_json({
                "type": "snapshot",
                "ts": datetime.now(timezone.utc).isoformat(),
                "state": state,
                "stats": journal.get_stats_today(),
                "trades": journal.get_recent_trades(10),
                "decisions": decisions,
                "signals": journal.get_recent_signals(5),
                "equity": journal.get_equity_curve(200),
                "profit": ProfitTracker.load("default").snapshot(),
                "alerts": journal.get_alerts(20),
                "alerts_unread": journal.get_unread_count(),
                "news": {
                    "blackout": news.get("blackout"),
                    "health": news.get("health", {}).get("sources", {}),
                    "headlines_count": len(news.get("headlines") or []),
                    "calendar_count": len(news.get("calendar") or []),
                    "sentiment": news.get("sentiment"),
                },
            })
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        mgr.disconnect(ws)
    except Exception:
        mgr.disconnect(ws)


@app.get("/api/ws-clients")
async def api_ws_clients():
    return {"clients": len(mgr.clients)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
