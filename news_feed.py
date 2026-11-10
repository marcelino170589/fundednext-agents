# news_feed.py
"""
Servicio unificado de noticias y fundamentales para FNL:004.

Objetivo: una sola fuente de verdad para calendario, titulares, sentimiento,
ventana de bloqueo y salud de fuentes. El módulo está pensado para no bloquear
el ciclo de trading: usa timeouts cortos, caché en memoria + disco y devuelve
datos marcados como *stale* cuando una fuente falla.

Fuentes:
  - Calendario: ForexFactory JSON semanal (nfs.faireconomy.media).
  - Titulares: Google News RSS (requests + feedparser) y Finnhub (opcional).
  - Sentimiento: heurístico local sobre titulares (lexicon-v1). No requiere API.
  - Opcional: fxnewsbias / tradekix se pueden conectar más adelante sin tocar
    el contrato de este módulo.

Contrato público (compatible con el código anterior):
  get_eventos_hoy(divisas=None) -> list[dict]
  get_titulares(symbol, horas=48) -> list[str]
  get_sentimiento(symbol) -> str
  ventana_bloqueada(symbol, minutos=15) -> (bool, str)
  build_fundamental_context(symbol) -> str
  get_calendario(activo) -> list[str]

Nuevo contrato para dashboard/API:
  get_snapshot(symbol, refresh=False, days=3) -> dict
  get_health() -> dict
  warm_up(background=True) -> None
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser
import requests

log = logging.getLogger("news_feed")

UTC = timezone.utc
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "data", "news_cache.json")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

HTTP_TIMEOUT = float(os.getenv("NEWS_HTTP_TIMEOUT", "8"))
CALENDAR_TTL = int(os.getenv("NEWS_CALENDAR_TTL", "900"))       # 15 min
HEADLINES_TTL = int(os.getenv("NEWS_HEADLINES_TTL", "900"))     # 15 min
MAX_HEADLINES = int(os.getenv("NEWS_MAX_HEADLINES", "12"))
MIN_RETRY_SECONDS = int(os.getenv("NEWS_MIN_RETRY_SECONDS", "60"))
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "").strip()

_lock = threading.RLock()
_cache: dict = {
    "calendar": [],
    "calendar_ts": 0.0,
    "calendar_attempt": 0.0,
    "headlines": {},
    "finnhub": {"ts": 0.0, "items": []},
    "saved_at": None,
}

_health: dict[str, dict] = {
    "calendar": {
        "label": "ForexFactory JSON", "status": "unknown", "count": 0,
        "latency_ms": None, "last_ok": None, "last_error": None,
        "last_attempt": None,
    },
    "google_news": {
        "label": "Google News RSS", "status": "unknown", "count": 0,
        "latency_ms": None, "last_ok": None, "last_error": None,
        "last_attempt": None,
    },
    "finnhub": {
        "label": "Finnhub", "status": "disabled" if not FINNHUB_KEY else "unknown",
        "count": 0, "latency_ms": None, "last_ok": None, "last_error": None,
        "last_attempt": None,
    },
}

_warm_started = False


# ═══════════════════════════════════════════════════════════════
# Utilidades de fecha / disco / salud
# ═══════════════════════════════════════════════════════════════

def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value) -> datetime | None:
    """Parsea ISO-8601 o RFC-822 y SIEMPRE devuelve UTC aware.

    El bug clásico del proyecto era quitar el offset con replace(tzinfo=None):
    un evento de ForexFactory a las 08:30-05:00 se interpretaba como 08:30 UTC
    (5 horas de error). Aquí se normaliza explícitamente a UTC.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except (ValueError, TypeError):
            try:
                dt = parsedate_to_datetime(text)
            except (ValueError, TypeError):
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _age_seconds(ts: float | None) -> int | None:
    if not ts:
        return None
    return max(0, int(time.time() - ts))


def _record(source: str, ok: bool, count: int = 0, latency_ms: float | None = None,
            error: str | None = None) -> None:
    with _lock:
        item = _health.setdefault(source, {
            "label": source, "status": "unknown", "count": 0, "latency_ms": None,
            "last_ok": None, "last_error": None, "last_attempt": None,
        })
        item["last_attempt"] = _iso(_now())
        if latency_ms is not None:
            item["latency_ms"] = round(float(latency_ms), 1)
        if ok:
            item["status"] = "ok"
            item["count"] = int(count)
            item["last_ok"] = _iso(_now())
            item["last_error"] = None
        else:
            item["status"] = "stale" if item.get("last_ok") else "error"
            item["last_error"] = (error or "error desconocido")[:300]


def _load_disk_cache() -> None:
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return
    except Exception as exc:
        log.debug("[news_feed] caché de disco ilegible: %s", exc)
        return

    with _lock:
        calendar = data.get("calendar") or []
        if isinstance(calendar, list):
            _cache["calendar"] = calendar
        _cache["calendar_ts"] = float(data.get("calendar_ts") or 0)
        headlines = data.get("headlines") or {}
        if isinstance(headlines, dict):
            _cache["headlines"] = headlines
        finnhub = data.get("finnhub") or {}
        if isinstance(finnhub, dict):
            _cache["finnhub"] = {
                "ts": float(finnhub.get("ts") or 0),
                "items": finnhub.get("items") or [],
            }
        health = data.get("health") or {}
        if isinstance(health, dict):
            for key, value in health.items():
                if key in _health and isinstance(value, dict):
                    _health[key].update(value)
        _cache["saved_at"] = data.get("saved_at")
    log.info("[news_feed] caché cargada (%s eventos, %s símbolos)",
             len(_cache["calendar"]), len(_cache["headlines"]))


def _save_disk_cache() -> None:
    with _lock:
        payload = {
            "version": 2,
            "saved_at": _iso(_now()),
            "calendar": _cache["calendar"],
            "calendar_ts": _cache["calendar_ts"],
            "headlines": _cache["headlines"],
            "finnhub": _cache["finnhub"],
            "health": _health,
        }
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, CACHE_FILE)
        _cache["saved_at"] = payload["saved_at"]
    except Exception as exc:
        log.debug("[news_feed] no se pudo guardar caché: %s", exc)


# ═══════════════════════════════════════════════════════════════
# Símbolos ↔ divisas
# ═══════════════════════════════════════════════════════════════

CURRENCIES = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNH", "CNY",
              "SGD", "MXN", "ZAR", "NOK", "SEK", "DKK", "HUF", "HKD")

INDEX_CURRENCIES = {
    "SPX500": {"USD"}, "NDX100": {"USD"}, "US30": {"USD"}, "US2000": {"USD"},
    "GER30": {"EUR"}, "FRA40": {"EUR"}, "EUSTX50": {"EUR"},
    "UK100": {"GBP"}, "SWI20": {"CHF"}, "JP225": {"JPY"},
    "HK50": {"CNY", "USD"}, "AUS200": {"AUD"},
}


def divisas_del_symbol(symbol: str) -> set[str]:
    """Divisas/países relevantes para un símbolo, alineadas con ForexFactory.

    ForexFactory usa códigos de divisa (USD, EUR, GBP, JPY…) como `country`,
    no códigos ISO de país (US, DE, GB…). El mapeo anterior de índices
    (GER30→DE) nunca casaba con el calendario.
    """
    s = (symbol or "").upper().strip()
    if not s:
        return set()
    if s.startswith(("XAU", "XAG", "XPT")):
        return {"USD"}
    if s in ("UKOUSD", "USOUSD"):
        return {"USD", "CAD"}
    if s in INDEX_CURRENCIES:
        return set(INDEX_CURRENCIES[s])
    # Pares FX: separar por códigos de 3 letras conocidos.
    if len(s) == 6:
        base, quote = s[:3], s[3:]
        if base in CURRENCIES and quote in CURRENCIES:
            return {base, quote}
    # Fallback para símbolos exóticos (ej. US30, NTH25).
    found = {c for c in CURRENCIES if c in s}
    return found or {s[:3]}


def _divisas_del_symbol(symbol: str) -> set[str]:
    """Alias de compatibilidad con el código anterior."""
    return divisas_del_symbol(symbol)


# ═══════════════════════════════════════════════════════════════
# 1. Calendario económico
# ═══════════════════════════════════════════════════════════════

def _fetch_calendar() -> list[dict]:
    started = time.time()
    try:
        response = requests.get(
            CALENDAR_URL, timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        raw = response.json()
        if not isinstance(raw, list):
            raise RuntimeError("respuesta JSON inesperada")

        events: list[dict] = []
        for item in raw:
            try:
                impact = str(item.get("impact", "")).strip()
                if impact.lower() not in ("high", "medium"):
                    continue
                dt = _parse_dt(item.get("date"))
                if not dt:
                    continue
                events.append({
                    "Date": _iso(dt),
                    "date_utc": _iso(dt),
                    "Currency": str(item.get("country", "")).upper(),
                    "Event": str(item.get("title", "")).strip(),
                    "Impact": impact.capitalize(),
                    "Importance": 3 if impact.lower() == "high" else 2,
                    "Actual": item.get("actual", "") or "",
                    "Forecast": item.get("forecast", "") or "",
                    "Previous": item.get("previous", "") or "",
                    "source": "forexfactory",
                })
            except Exception:
                continue

        events.sort(key=lambda e: e["date_utc"])
        _record("calendar", True, len(events), (time.time() - started) * 1000)
        log.info("[news_feed] calendario: %s eventos (%.2fs)",
                 len(events), time.time() - started)
        return events
    except Exception as exc:
        _record("calendar", False, 0, (time.time() - started) * 1000, str(exc))
        log.warning("[news_feed] calendario no disponible: %s", exc)
        return []


def refresh_calendar(force: bool = False) -> list[dict]:
    """Refresca el calendario respetando TTL y un backoff tras fallos."""
    now = time.time()
    with _lock:
        fresh = bool(_cache["calendar"]) and (now - _cache["calendar_ts"] < CALENDAR_TTL)
        last_attempt = float(_cache.get("calendar_attempt") or 0)
        cached = list(_cache["calendar"])
    if fresh and not force:
        return cached
    if not force and (now - last_attempt) < MIN_RETRY_SECONDS:
        return cached

    with _lock:
        _cache["calendar_attempt"] = now
    events = _fetch_calendar()
    with _lock:
        if events:
            _cache["calendar"] = events
            _cache["calendar_ts"] = time.time()
        # Si falla, conservamos el calendario anterior (stale) para no cegar
        # al agente fundamental ni al dashboard.
        result = list(_cache["calendar"])
    if events or not cached:
        _save_disk_cache()
    return result


def _filter_calendar(events: list[dict], *, days: int, include_medium: bool,
                     currencies: set[str] | None,
                     include_past_hours: int = 2) -> list[dict]:
    now = _now()
    start = now - timedelta(hours=include_past_hours)
    end = now + timedelta(days=max(1, min(int(days or 3), 7)))
    out: list[dict] = []
    for event in events:
        dt = _parse_dt(event.get("Date") or event.get("date_utc"))
        if not dt or not (start <= dt <= end):
            continue
        importance = int(event.get("Importance") or 0)
        if not include_medium and importance < 3:
            continue
        if currencies and str(event.get("Currency", "")).upper() not in currencies:
            continue
        row = dict(event)
        row["dt_utc"] = _iso(dt)
        row["minutes_to"] = int((dt - now).total_seconds() // 60)
        out.append(row)
    out.sort(key=lambda e: e.get("dt_utc") or "")
    return out


def get_calendar(days: int = 3, include_medium: bool = True,
                 currencies: set[str] | None = None,
                 force: bool = False,
                 include_past_hours: int = 2) -> list[dict]:
    events = refresh_calendar(force=force)
    return _filter_calendar(
        events, days=days, include_medium=include_medium,
        currencies=currencies, include_past_hours=include_past_hours,
    )


def get_eventos_hoy(divisas: list[str] | None = None) -> list[dict]:
    """Compatibilidad: eventos de ALTO impacto de las próximas 48 h."""
    currencies = {d.upper() for d in divisas} if divisas else None
    return get_calendar(days=2, include_medium=False, currencies=currencies)


# ═══════════════════════════════════════════════════════════════
# 2. Ventana de bloqueo por noticias
# ═══════════════════════════════════════════════════════════════

def _blackout_minutes(minutos: int | None) -> int:
    if minutos is not None:
        return max(1, int(minutos))
    try:
        from config import NEWS_BLACKOUT_MIN
        return max(1, int(NEWS_BLACKOUT_MIN))
    except Exception:
        return max(1, int(os.getenv("NEWS_BLACKOUT_MIN", "15")))


def _blackout_from_events(events: list[dict], symbol: str,
                          minutes: int) -> dict:
    currencies = divisas_del_symbol(symbol)
    now = _now()
    nearest = None
    nearest_delta = None
    for event in events:
        dt = _parse_dt(event.get("Date") or event.get("dt_utc"))
        if not dt:
            continue
        delta_min = (dt - now).total_seconds() / 60
        if nearest_delta is None or abs(delta_min) < abs(nearest_delta):
            nearest, nearest_delta = event, delta_min
        if abs(delta_min) <= minutes:
            return {
                "blocked": True,
                "minutes": minutes,
                "minutes_to": round(delta_min, 1),
                "event": event,
                "reason": (f"{event.get('Event')} ({event.get('Currency')}) "
                           f"{'en' if delta_min >= 0 else 'hace'} "
                           f"{abs(delta_min):.0f} min"),
                "currencies": sorted(currencies),
            }
    return {
        "blocked": False,
        "minutes": minutes,
        "minutes_to": round(nearest_delta, 1) if nearest_delta is not None else None,
        "event": nearest,
        "reason": "",
        "currencies": sorted(currencies),
    }


def get_blackout(symbol: str, minutos: int | None = None) -> dict:
    """Estado estructurado de la ventana de bloqueo ±N minutos."""
    minutes = _blackout_minutes(minutos)
    currencies = divisas_del_symbol(symbol)
    events = get_calendar(days=2, include_medium=False, currencies=currencies)
    return _blackout_from_events(events, symbol, minutes)


def ventana_bloqueada(symbol: str, minutos: int | None = None) -> tuple[bool, str]:
    state = get_blackout(symbol, minutos)
    return bool(state["blocked"]), state.get("reason", "")


# ═══════════════════════════════════════════════════════════════
# 3. Titulares: Google News RSS + Finnhub
# ═══════════════════════════════════════════════════════════════

_QUERIES = {
    "XAUUSD": "gold price OR XAUUSD OR bullion OR Federal Reserve OR inflation",
    "XAGUSD": "silver price OR XAGUSD OR precious metals OR Federal Reserve",
    "XPTUSD": "platinum price OR XPTUSD OR precious metals",
    "UKOUSD": "Brent crude oil OR OPEC OR oil supply",
    "USOUSD": "WTI crude oil OR OPEC OR oil prices",
    "EURUSD": "EURUSD OR euro OR European Central Bank",
    "GBPUSD": "GBPUSD OR British pound OR Bank of England",
    "USDJPY": "USDJPY OR Japanese yen OR Bank of Japan",
    "USDCAD": "USDCAD OR Canadian dollar OR Bank of Canada OR oil",
    "USDCHF": "USDCHF OR Swiss franc OR Swiss National Bank",
    "AUDUSD": "AUDUSD OR Australian dollar OR Reserve Bank of Australia",
    "NZDUSD": "NZDUSD OR New Zealand dollar OR Reserve Bank of New Zealand",
    "SPX500": "S&P 500 OR Wall Street OR US stocks OR Federal Reserve",
    "NDX100": "Nasdaq OR tech stocks OR US stocks OR Federal Reserve",
    "US30": "Dow Jones OR US stocks OR Wall Street",
    "US2000": "Russell 2000 OR US small caps OR US stocks",
    "GER30": "DAX OR German stocks OR European stocks OR ECB",
    "UK100": "FTSE 100 OR UK stocks OR Bank of England",
    "FRA40": "CAC 40 OR French stocks OR European stocks",
    "EUSTX50": "Euro Stoxx 50 OR European stocks OR ECB",
    "SWI20": "Swiss stocks OR SMI OR Swiss National Bank",
    "JP225": "Nikkei OR Japanese stocks OR Bank of Japan",
    "HK50": "Hang Seng OR Hong Kong stocks OR China markets",
    "AUS200": "ASX 200 OR Australian stocks OR Reserve Bank of Australia",
}


def _query_for(symbol: str) -> str:
    s = symbol.upper()
    if s in _QUERIES:
        return _QUERIES[s]
    currencies = sorted(divisas_del_symbol(s))
    if len(currencies) >= 2:
        return f"{s} forex OR {currencies[0]} {currencies[1]}"
    return f"{s} markets OR forex"


_ASSET_TERMS: dict[str, list[str]] = {
    "XAUUSD": ["gold", "xauusd", "xau", "bullion", "precious metal", "oro", "safe haven"],
    "XAGUSD": ["silver", "xagusd", "xag", "bullion", "precious metal", "plata"],
    "XPTUSD": ["platinum", "xptusd", "xpt", "precious metal", "platino"],
    "UKOUSD": ["brent", "oil", "crude", "opec", "energy", "petroleum"],
    "USOUSD": ["wti", "oil", "crude", "opec", "energy", "petroleum"],
    "SPX500": ["s&p", "s&p 500", "stocks", "wall street", "equities", "earnings"],
    "NDX100": ["nasdaq", "tech stocks", "stocks", "wall street", "equities"],
    "US30": ["dow", "dow jones", "stocks", "wall street", "equities"],
    "US2000": ["russell", "small caps", "stocks", "wall street"],
    "GER30": ["dax", "german stocks", "european stocks", "euro"],
    "UK100": ["ftse", "uk stocks", "british stocks"],
    "FRA40": ["cac", "french stocks", "european stocks"],
    "EUSTX50": ["euro stoxx", "european stocks", "euro"],
    "SWI20": ["smi", "swiss stocks", "swiss"],
    "JP225": ["nikkei", "japanese stocks", "japan stocks"],
    "HK50": ["hang seng", "hong kong stocks", "china stocks"],
    "AUS200": ["asx", "australian stocks", "australia stocks"],
}

_CURRENCY_WORDS = {
    "USD": ["dollar", "usd", "greenback", "fed", "fomc", "powell"],
    "EUR": ["euro", "eur", "ecb", "lagarde", "eurozone"],
    "GBP": ["pound", "sterling", "gbp", "boe", "bailey", "britain", "uk"],
    "JPY": ["yen", "jpy", "boj", "ueda", "japan"],
    "CAD": ["canadian dollar", "loonie", "cad", "boc", "canada"],
    "AUD": ["australian dollar", "aussie", "aud", "rba", "australia"],
    "NZD": ["new zealand dollar", "kiwi", "nzd", "rbnz", "new zealand"],
    "CHF": ["swiss franc", "franc", "chf", "snb", "swiss"],
    "CNY": ["yuan", "renminbi", "cny", "china", "pboc"],
    "CNH": ["yuan", "renminbi", "cnh", "china", "pboc"],
}

_MACRO_TERMS = [
    "fed", "fomc", "powell", "inflation", "cpi", "pce", "rates", "interest rate",
    "treasury", "yields", "central bank", "ecb", "boe", "boj", "rba", "rbnz",
    "boc", "snb", "recession", "gdp", "payrolls", "employment", "tariff",
    "geopolitical", "war", "sanctions", "oil", "dollar",
]

_UNRELATED = [
    "bitcoin", "btc", "ethereum", "crypto", "nft", "celebrity", "sports",
    "football", "basketball", "movie", "music", "lottery", "royal family",
]


def _word_in(text: str, term: str) -> bool:
    if not term:
        return False
    if " " in term or "&" in term:
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _relevance(title: str, symbol: str) -> float:
    text = (title or "").lower()
    if not text:
        return 0.0
    s = symbol.upper()
    score = 0.0
    if _word_in(text, s.lower()):
        score += 6.0
    for term in _ASSET_TERMS.get(s, []):
        if _word_in(text, term):
            score += 3.0
    currencies = divisas_del_symbol(s)
    for currency in currencies:
        for word in _CURRENCY_WORDS.get(currency, []):
            if _word_in(text, word):
                score += 2.0
                break
    for term in _MACRO_TERMS:
        if _word_in(text, term):
            score += 1.0
    for term in _UNRELATED:
        if _word_in(text, term):
            score -= 6.0
    return round(score, 2)


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _google_news_items(query: str) -> list[dict]:
    started = time.time()
    url = (
        "https://news.google.com/rss/search?q="
        f"{quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        response = requests.get(url, timeout=HTTP_TIMEOUT,
                                headers={"User-Agent": USER_AGENT})
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        feed = feedparser.parse(response.content)
        items: list[dict] = []
        for entry in getattr(feed, "entries", [])[:40]:
            title = _strip_html(entry.get("title", ""))
            if not title:
                continue
            source = ""
            raw_source = entry.get("source")
            if isinstance(raw_source, dict):
                source = raw_source.get("title", "") or ""
            source = source or "Google News"
            # Google News suele añadir " - Fuente" al final del título.
            if source and title.endswith(f" - {source}"):
                title = title[: -(len(source) + 3)].strip()
            published = None
            parsed = entry.get("published_parsed")
            if parsed:
                try:
                    published = datetime(*parsed[:6], tzinfo=UTC)
                except Exception:
                    published = None
            if published is None:
                published = _parse_dt(entry.get("published"))
            items.append({
                "title": title,
                "url": entry.get("link", ""),
                "source": source,
                "published": _iso(published),
                "summary": _strip_html(entry.get("summary", ""))[:280],
                "origin": "google_news",
            })
        _record("google_news", True, len(items), (time.time() - started) * 1000)
        return items
    except Exception as exc:
        _record("google_news", False, 0, (time.time() - started) * 1000, str(exc))
        log.warning("[news_feed] Google News no disponible: %s", exc)
        return []


def _finnhub_items() -> list[dict]:
    if not FINNHUB_KEY:
        return []
    now = time.time()
    with _lock:
        if _cache["finnhub"]["items"] and (now - _cache["finnhub"]["ts"] < HEADLINES_TTL):
            return list(_cache["finnhub"]["items"])

    started = time.time()
    try:
        response = requests.get(
            f"https://finnhub.io/api/v1/news?category=forex&token={FINNHUB_KEY}",
            timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT},
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        items = []
        for row in response.json()[:40]:
            items.append({
                "title": _strip_html(row.get("headline", "")),
                "url": row.get("url", ""),
                "source": row.get("source", "Finnhub"),
                "published": _iso(datetime.fromtimestamp(
                    row.get("datetime", 0), tz=UTC)) if row.get("datetime") else None,
                "summary": _strip_html(row.get("summary", ""))[:280],
                "origin": "finnhub",
            })
        with _lock:
            _cache["finnhub"] = {"ts": time.time(), "items": items}
        _record("finnhub", True, len(items), (time.time() - started) * 1000)
        return items
    except Exception as exc:
        _record("finnhub", False, 0, (time.time() - started) * 1000, str(exc))
        log.warning("[news_feed] Finnhub no disponible: %s", exc)
        return []


def _norm_title(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"[^a-z0-9áéíóúüñ ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(title: str) -> set[str]:
    return {t for t in _norm_title(title).split() if len(t) > 3}


def _dedupe(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    for item in items:
        key = _norm_title(item.get("title", ""))
        if not key:
            continue
        tokens = _tokens(item.get("title", ""))
        duplicate = False
        for kept in result:
            if key == _norm_title(kept.get("title", "")):
                duplicate = True
                break
            kept_tokens = _tokens(kept.get("title", ""))
            if tokens and kept_tokens:
                union = tokens | kept_tokens
                if union and len(tokens & kept_tokens) / len(union) >= 0.8:
                    duplicate = True
                    break
        if not duplicate:
            result.append(item)
    return result


def _rank_headlines(items: list[dict], symbol: str) -> list[dict]:
    ranked = []
    now = _now()
    for item in items:
        relevance = _relevance(item.get("title", ""), symbol)
        if relevance <= 0:
            continue
        published = _parse_dt(item.get("published"))
        age_h = (now - published).total_seconds() / 3600 if published else 48.0
        recency = max(0.0, 24.0 - age_h) / 24.0
        row = dict(item)
        row["relevance"] = relevance
        row["age_hours"] = round(age_h, 1) if published else None
        row["impact"] = _headline_impact(item.get("title", ""), symbol)
        row["rank"] = round(relevance + recency * 2.0, 2)
        ranked.append(row)
    ranked.sort(key=lambda x: (x["rank"], x.get("published") or ""), reverse=True)
    return _dedupe(ranked)[:MAX_HEADLINES]


def get_headlines(symbol: str = "XAUUSD", force: bool = False) -> list[dict]:
    symbol = (symbol or "XAUUSD").upper()
    now = time.time()
    with _lock:
        entry = _cache["headlines"].get(symbol)
        if entry and not force and (now - float(entry.get("ts") or 0) < HEADLINES_TTL):
            return list(entry.get("items") or [])
        last_attempt = float(entry.get("attempt") or 0) if entry else 0.0
        stale_items = list(entry.get("items") or []) if entry else []
    if not force and (now - last_attempt) < MIN_RETRY_SECONDS:
        return stale_items

    with _lock:
        entry = _cache["headlines"].setdefault(symbol, {})
        entry["attempt"] = now
        entry["query"] = _query_for(symbol)

    query = _query_for(symbol)
    items = _google_news_items(query)
    items.extend(_finnhub_items())
    ranked = _rank_headlines(items, symbol)

    with _lock:
        entry = _cache["headlines"].setdefault(symbol, {})
        if ranked:
            entry.update({
                "ts": time.time(),
                "items": ranked,
                "stale": False,
                "query": query,
                "fetched_at": _iso(_now()),
            })
        else:
            # Sin resultados nuevos: conservamos los anteriores y los marcamos
            # como stale para que el dashboard lo muestre sin ocultar el fallo.
            if not entry.get("items"):
                entry.update({"ts": time.time(), "items": [], "stale": False,
                              "query": query, "fetched_at": _iso(_now())})
            else:
                entry["stale"] = True
                entry["last_empty_at"] = _iso(_now())
    if ranked:
        _save_disk_cache()
    log.info("[news_feed] %s: %s titulares relevantes (%s)", symbol, len(ranked), query)
    return ranked


def get_headlines_meta(symbol: str) -> dict:
    symbol = (symbol or "XAUUSD").upper()
    with _lock:
        entry = _cache["headlines"].get(symbol) or {}
        items = list(entry.get("items") or [])
        return {
            "symbol": symbol,
            "count": len(items),
            "stale": bool(entry.get("stale")),
            "query": entry.get("query") or _query_for(symbol),
            "fetched_at": entry.get("fetched_at"),
            "age_sec": _age_seconds(entry.get("ts")),
            "sources": sorted({i.get("origin", "?") for i in items}),
        }


# ═══════════════════════════════════════════════════════════════
# 4. Sentimiento heurístico (lexicon-v1)
# ═══════════════════════════════════════════════════════════════

_POS_WORDS = [
    "surge", "surges", "soar", "soars", "rally", "rallies", "gain", "gains",
    "rise", "rises", "climb", "climbs", "jump", "jumps", "advance", "advances",
    "strong", "strength", "upbeat", "optimism", "record high", "beat", "beats",
    "boost", "boosts", "demand", "inflows", "buying", "support", "recovery",
    "rebound", "higher",
]
_NEG_WORDS = [
    "plunge", "plunges", "slump", "slumps", "fall", "falls", "drop", "drops",
    "slide", "slides", "decline", "declines", "weak", "weakness", "miss",
    "misses", "fear", "fears", "selloff", "sell-off", "recession", "crisis",
    "tariff", "tariffs", "war", "downgrade", "outflows", "pressure", "gloom",
    "lower", "risk-off", "flight to safety", "uncertainty",
]
# Términos específicos de divisas. No se usan para índices porque "dovish"
# puede ser alcista para bolsa y bajista para una divisa.
_CURRENCY_POS = _POS_WORDS + [
    "hawkish", "rate hike", "rate hikes", "tightening", "stronger",
    "strengthens", "strengthening", "higher for longer",
]
_CURRENCY_NEG = _NEG_WORDS + [
    "dovish", "rate cut", "rate cuts", "easing", "weaker", "weakens",
    "weakening", "stimulus",
]
_GOLD_UP = ["safe haven", "safe-haven", "haven demand", "central bank buying",
            "etf inflows", "record high", "bullion rises", "gold rises"]
_GOLD_DOWN = ["real yields", "profit-taking", "etf outflows", "gold falls",
              "gold drops", "strong dollar", "hawkish fed"]
_RISK_ON = ["risk-on", "risk appetite", "stocks rally", "equities rally",
            "optimism", "earnings beat"]
_RISK_OFF = ["risk-off", "flight to safety", "stocks fall", "stocks slide",
             "selloff", "recession fears", "geopolitical", "war"]
_OIL_UP = ["opec cuts", "supply cut", "supply disruption", "inventory draw",
           "oil rises", "crude rises", "demand strong"]
_OIL_DOWN = ["opec increases", "inventory build", "demand worries",
             "oil falls", "crude falls", "oversupply"]


def _currency_tones(title: str) -> dict[str, float]:
    """Tono por divisa usando el verbo que sigue al nombre (±30 chars) y
    adjetivos inmediatamente anteriores ("strong dollar", "dovish Fed").

    Mirar una ventana simétrica amplia contaba el verbo del activo como si
    fuera de la divisa: "Gold, silver advance as dollar weakens" marcaba al
    USD como fuerte por el "advance" de Gold. Aquí el verbo posterior manda.
    """
    text = (title or "").lower()
    tones: dict[str, float] = {}
    adjectives_pos = ("strong", "stronger", "strengthening", "hawkish", "higher")
    adjectives_neg = ("weak", "weaker", "weakening", "dovish", "lower")
    for currency, words in _CURRENCY_WORDS.items():
        for word in words:
            for match in re.finditer(rf"\b{re.escape(word)}\b", text):
                value = 0.0
                after = text[match.end(): match.end() + 30]
                before = text[max(0, match.start() - 18): match.start()]
                if any(_word_in(after, w) for w in _CURRENCY_POS):
                    value += 1.0
                if any(_word_in(after, w) for w in _CURRENCY_NEG):
                    value -= 1.0
                if not value:
                    if any(_word_in(before.strip(), w) for w in adjectives_pos):
                        value += 0.8
                    elif any(_word_in(before.strip(), w) for w in adjectives_neg):
                        value -= 0.8
                if value:
                    tones[currency] = tones.get(currency, 0.0) + value
                    break
    return tones


def _headline_impact(title: str, symbol: str) -> float:
    text = (title or "").lower()
    s = symbol.upper()
    score = 0.0

    for word in _POS_WORDS:
        if _word_in(text, word):
            score += 0.5
    for word in _NEG_WORDS:
        if _word_in(text, word):
            score -= 0.5

    tones = _currency_tones(title)
    currencies = divisas_del_symbol(s)
    if s.startswith(("XAU", "XAG", "XPT")):
        # Metal: el precio sube si el USD se debilita y baja si el USD se fortalece.
        usd = tones.get("USD", 0.0)
        score -= usd * 1.4
        if s.startswith("XAU"):
            if any(_word_in(text, w) for w in _GOLD_UP):
                score += 1.5
            if any(_word_in(text, w) for w in _GOLD_DOWN):
                score -= 1.5
    elif s in ("UKOUSD", "USOUSD"):
        if any(_word_in(text, w) for w in _OIL_UP):
            score += 1.4
        if any(_word_in(text, w) for w in _OIL_DOWN):
            score -= 1.4
        score -= tones.get("USD", 0.0) * 0.5
    elif s in INDEX_CURRENCIES:
        if any(_word_in(text, w) for w in _RISK_ON):
            score += 1.2
        if any(_word_in(text, w) for w in _RISK_OFF):
            score -= 1.2
        score -= tones.get("USD", 0.0) * 0.3
    elif len(currencies) >= 2:
        # Par FX: fortaleza de la base menos fortaleza de la cotizada.
        base, quote = s[:3], s[3:6]
        # La fortaleza de la base frente a la cotizada ya incluye al USD;
        # no se vuelve a restar para evitar doble conteo.
        score += (tones.get(base, 0.0) - tones.get(quote, 0.0)) * 1.4

    return max(-3.0, min(3.0, round(score, 2)))


def get_sentiment(symbol: str = "XAUUSD", items: list[dict] | None = None) -> dict:
    symbol = (symbol or "XAUUSD").upper()
    if items is None:
        items = get_headlines(symbol)
    now = _now()
    if not items:
        return {
            "available": False, "label": "SIN DATOS", "score": 0, "confidence": 0,
            "headlines_analyzed": 0, "positives": 0, "negatives": 0, "neutrals": 0,
            "method": "lexicon-v1", "drivers": [],
            "summary": "Sin titulares: el sentimiento no se usa como veto.",
        }

    weighted_sum = 0.0
    max_sum = 0.0
    positives = negatives = neutrals = 0
    drivers: list[dict] = []
    for item in items:
        impact = _headline_impact(item.get("title", ""), symbol)
        published = _parse_dt(item.get("published"))
        age_h = (now - published).total_seconds() / 3600 if published else 48.0
        weight = (1.0 + min(item.get("relevance", 0), 10) / 10.0) * (0.6 if age_h > 24 else 1.0)
        weighted_sum += impact * weight
        max_sum += 3.0 * weight
        if impact > 0.4:
            positives += 1
        elif impact < -0.4:
            negatives += 1
        else:
            neutrals += 1
        drivers.append({
            "title": item.get("title", ""),
            "impact": impact,
            "source": item.get("source", ""),
            "url": item.get("url", ""),
        })

    score = round(100 * weighted_sum / max_sum) if max_sum else 0
    label = "BULLISH" if score >= 20 else "BEARISH" if score <= -20 else "NEUTRAL"
    analyzed = len(items)
    agreement = abs(positives - negatives) / analyzed if analyzed else 0
    confidence = min(95, round(25 + analyzed * 6 + agreement * 20)) if analyzed else 0
    drivers.sort(key=lambda d: abs(d["impact"]), reverse=True)
    return {
        "available": True,
        "label": label,
        "score": int(score),
        "confidence": int(confidence),
        "headlines_analyzed": analyzed,
        "positives": positives,
        "negatives": negatives,
        "neutrals": neutrals,
        "method": "lexicon-v1",
        "drivers": drivers[:4],
        "summary": (f"{label} ({score:+d}/100) · {positives} alcistas, "
                    f"{negatives} bajistas, {neutrals} neutras · heurístico"),
    }


def get_sentimiento(symbol: str = "XAUUSD") -> str:
    """Compatibilidad: sentimiento como texto para el contexto del LLM."""
    sent = get_sentiment(symbol)
    if not sent.get("available"):
        return "Sin titulares: sentimiento no disponible (no se usa como veto)."
    return (f"{sent['label']} (score {sent['score']:+d}/100, "
            f"{sent['headlines_analyzed']} titulares, heurístico)")


# ═══════════════════════════════════════════════════════════════
# 5. Snapshot para API / dashboard
# ═══════════════════════════════════════════════════════════════

def get_health() -> dict:
    with _lock:
        health = json.loads(json.dumps(_health))
        calendar_age = _age_seconds(_cache["calendar_ts"])
        headlines_age = {
            symbol: _age_seconds((entry or {}).get("ts"))
            for symbol, entry in _cache["headlines"].items()
        }
        return {
            "sources": health,
            "calendar_age_sec": calendar_age,
            "calendar_count": len(_cache["calendar"]),
            "headlines_symbols": len(_cache["headlines"]),
            "headlines_age_sec": headlines_age,
            "saved_at": _cache.get("saved_at"),
        }


def get_snapshot(symbol: str = "XAUUSD", *, refresh: bool = False,
                 days: int = 3, include_medium: bool = True) -> dict:
    symbol = (symbol or "XAUUSD").upper()
    force = bool(refresh)
    if force:
        refresh_calendar(force=True)
        get_headlines(symbol, force=True)

    calendar = get_calendar(days=days, include_medium=include_medium,
                            force=False, include_past_hours=2)
    currencies = divisas_del_symbol(symbol)
    calendar_symbol = [e for e in calendar if e.get("Currency") in currencies]
    headlines = get_headlines(symbol)
    sentiment = get_sentiment(symbol)
    blackout = get_blackout(symbol)
    return {
        "symbol": symbol,
        "currencies": sorted(currencies),
        "generated_at": _iso(_now()),
        "calendar": calendar,
        "calendar_symbol": calendar_symbol,
        "headlines": headlines,
        "headlines_meta": get_headlines_meta(symbol),
        "sentiment": sentiment,
        "blackout": blackout,
        "health": get_health(),
        "next_high_impact": blackout.get("event"),
        "disclaimer": ("Sentimiento heurístico sobre titulares; no es asesoría "
                       "financiera ni una predicción."),
    }


def peek_snapshot(symbol: str = "XAUUSD", days: int = 3) -> dict:
    """Snapshot SIN red: solo caché. Se usa en el WebSocket cada 2 s."""
    symbol = (symbol or "XAUUSD").upper()
    with _lock:
        raw_calendar = list(_cache["calendar"])
        entry = _cache["headlines"].get(symbol) or {}
        items = list(entry.get("items") or [])
    calendar = _filter_calendar(raw_calendar, days=days, include_medium=True,
                                currencies=None, include_past_hours=2)
    currencies = divisas_del_symbol(symbol)
    calendar_symbol = [e for e in calendar if e.get("Currency") in currencies]
    high_events = [e for e in calendar_symbol if int(e.get("Importance") or 0) >= 3]
    blackout = _blackout_from_events(high_events, symbol, _blackout_minutes(None))
    sentiment = get_sentiment(symbol, items=items)
    return {
        "symbol": symbol,
        "currencies": sorted(currencies),
        "generated_at": _iso(_now()),
        "calendar": calendar,
        "calendar_symbol": calendar_symbol,
        "headlines": items,
        "headlines_meta": get_headlines_meta(symbol),
        "sentiment": sentiment,
        "blackout": blackout,
        "health": get_health(),
        "next_high_impact": blackout.get("event"),
        "cached": True,
    }


def build_fundamental_context(symbol: str) -> str:
    """Contexto compacto y trazable para el agente fundamental (LLM)."""
    snapshot = get_snapshot(symbol, days=2, include_medium=False)
    now = _now()
    lines = [f"=== CONTEXTO FUNDAMENTAL: {symbol} ===",
             f"Fecha UTC: {now.isoformat()}",
             f"Divisas relevantes: {', '.join(snapshot['currencies']) or '—'}",
             ""]

    health = snapshot["health"]["sources"]
    cal_health = health.get("calendar", {})
    gnews = health.get("google_news", {})
    lines.append("--- ESTADO DE FUENTES ---")
    lines.append(f"Calendario: {cal_health.get('status', '?')} · "
                 f"{cal_health.get('count', 0)} eventos · "
                 f"latencia {cal_health.get('latency_ms') or '—'} ms")
    lines.append(f"Titulares: {gnews.get('status', '?')} · "
                 f"{snapshot['headlines_meta'].get('count', 0)} relevantes · "
                 f"fuente {', '.join(snapshot['headlines_meta'].get('sources') or ['—'])}")
    if snapshot["headlines_meta"].get("stale"):
        lines.append("AVISO: titulares en caché (fuente no actualizada).")
    lines.append("")

    lines.append("--- CALENDARIO ECONÓMICO (alto impacto, próximas 48 h) ---")
    if snapshot["calendar_symbol"]:
        for event in snapshot["calendar_symbol"][:10]:
            when = _parse_dt(event.get("Date"))
            when_txt = when.strftime("%Y-%m-%d %H:%M UTC") if when else "—"
            actual = event.get("Actual") or "N/A"
            forecast = event.get("Forecast") or "N/A"
            previous = event.get("Previous") or "N/A"
            lines.append(f"- {when_txt} | {event.get('Currency')} | "
                         f"{event.get('Event')} | Actual: {actual} | "
                         f"Forecast: {forecast} | Previo: {previous}")
    else:
        lines.append("- Sin eventos de alto impacto disponibles para este activo.")
    lines.append("")

    lines.append("--- TITULARES RECIENTES (relevancia / fuente / hora) ---")
    if snapshot["headlines"]:
        for item in snapshot["headlines"][:8]:
            published = _parse_dt(item.get("published"))
            when_txt = published.strftime("%H:%M UTC") if published else "—"
            lines.append(f"- [{item.get('relevance', 0)}] [{item.get('source') or '?'} "
                         f"{when_txt}] {item.get('title')}")
    else:
        lines.append("- Sin titulares disponibles para este activo.")
    lines.append("")

    sentiment = snapshot["sentiment"]
    lines.append("--- SENTIMIENTO DE DIVISAS (heurístico) ---")
    lines.append(sentiment.get("summary", "Sin datos."))
    if sentiment.get("drivers"):
        for driver in sentiment["drivers"][:3]:
            lines.append(f"  · impact {driver['impact']:+.1f}: {driver['title'][:140]}")
    lines.append("")

    lines.append("--- VENTANA DE BLOQUEO ---")
    blackout = snapshot["blackout"]
    if blackout.get("blocked"):
        lines.append(f"BLOQUEADO: {blackout.get('reason')} (ventana ±{blackout.get('minutes')} min).")
    elif blackout.get("event"):
        event = blackout["event"]
        lines.append(f"Sin bloqueo. Próximo evento alto impacto: {event.get('Event')} "
                     f"({event.get('Currency')}) en {blackout.get('minutes_to')} min.")
    else:
        lines.append("Sin bloqueo y sin eventos de alto impacto próximos.")
    lines.append("")
    lines.append("REGLA: si no hay datos de noticias, responde NEUTRAL; no bloquees "
                 "la operación solo por falta de información.")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 6. Calentamiento de caché
# ═══════════════════════════════════════════════════════════════

def warm_up(background: bool = True) -> None:
    """Precarga calendario y titulares para que el dashboard responda rápido."""
    global _warm_started
    if _warm_started:
        return
    _warm_started = True

    def _run() -> None:
        try:
            refresh_calendar()
            for symbol in ("XAUUSD", "EURUSD", "USDJPY", "USDCAD"):
                get_headlines(symbol)
            log.info("[news_feed] warm-up completado")
        except Exception as exc:
            log.warning("[news_feed] warm-up incompleto: %s", exc)

    if background:
        threading.Thread(target=_run, name="news-warmup", daemon=True).start()
    else:
        _run()


# ═══════════════════════════════════════════════════════════════
# 7. Compatibilidad con el código anterior
# ═══════════════════════════════════════════════════════════════

def get_titulares(symbol: str, horas: int = 12) -> list[str]:
    """Compatibilidad: devuelve solo títulos (el código viejo esperaba str)."""
    return [item.get("title", "") for item in get_headlines(symbol) if item.get("title")]


def get_calendario(activo: str) -> list[str]:
    """Compatibilidad con news_feed_temp.py / dashboard."""
    currencies = divisas_del_symbol(activo)
    events = get_calendar(days=2, include_medium=False, currencies=currencies)
    return [
        f"{str(e.get('Date', ''))[:16]} | {e.get('Currency')} | "
        f"{e.get('Event')} | Actual: {e.get('Actual') or 'N/A'}"
        for e in events[:10]
    ]


_load_disk_cache()
