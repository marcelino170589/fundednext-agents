# llm_router.py
"""
Router multi-proveedor compatible con OpenAI para los agentes FNL:004.

La lista https://github.com/mnfst/awesome-free-llm-apis no es una librería:
es un catálogo de APIs con free tier. Este módulo convierte ese catálogo en
algo usable: lee varios proveedores/claves desde `.env` o un JSON, ordena por
prioridad, rota claves, aplica cooldowns y cae al siguiente proveedor si uno
falla, devuelve JSON inválido o agota su cuota.

No ejecuta órdenes ni toca el EA. Solo sustituye la llamada al LLM.

Configuración rápida (`.env`):

    LLM_ROUTER_ENABLED=true
    LLM_PROVIDER_1_NAME=groq
    LLM_PROVIDER_1_BASE_URL=https://api.groq.com/openai/v1
    LLM_PROVIDER_1_MODEL=openai/gpt-oss-20b
    LLM_PROVIDER_1_API_KEYS=key1,key2
    LLM_PROVIDER_1_PRIORITY=10
    LLM_PROVIDER_1_JSON_MODE=true

    LLM_PROVIDER_2_NAME=gemini
    LLM_PROVIDER_2_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
    LLM_PROVIDER_2_MODEL=gemini-2.5-flash
    LLM_PROVIDER_2_API_KEY=...
    LLM_PROVIDER_2_PRIORITY=20

    # Fallback de pago (Meta Model API / Muse Spark)
    LLM_PROVIDER_9_NAME=meta
    LLM_PROVIDER_9_BASE_URL=https://api.meta.ai/v1
    LLM_PROVIDER_9_MODEL=muse-spark-1.3
    LLM_PROVIDER_9_API_KEY=...
    LLM_PROVIDER_9_PRIORITY=90

Alternativa: `LLM_PROVIDERS_FILE=/ruta/llm_providers.json` con una lista de
objetos {name, base_url, model, api_keys, priority, json_mode, extra_headers}.

Seguridad:
  - Las claves nunca se escriben en logs ni en el estado persistido.
  - Los free tiers pueden usar tus prompts para entrenar; revisa sus términos
    antes de enviar datos de cuentas o de clientes.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_ROUTER_ENABLED,
    LLM_PROVIDERS_FILE,
    LLM_ROUTER_MAX_ATTEMPTS,
    LLM_ROUTER_COOLDOWN_SEC,
    LLM_ROUTER_TIMEOUT,
    LLM_ROUTER_STATE_FILE,
)

log = logging.getLogger("llm_router")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ═══════════════════════════════════════════════════════════════
# Modelo de configuración
# ═══════════════════════════════════════════════════════════════

@dataclass
class Provider:
    name: str
    base_url: str
    model: str
    api_keys: list[str] = field(default_factory=list)
    priority: int = 100
    json_mode: bool = True
    enabled: bool = True
    timeout: float = LLM_ROUTER_TIMEOUT
    max_tokens: int | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)

    # Runtime (no se serializa con claves)
    key_state: dict = field(default_factory=dict)
    calls: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    last_error: str | None = None
    last_latency_ms: float | None = None
    last_success_at: float | None = None

    def state_for(self, key: str) -> dict:
        return self.key_state.setdefault(key, {
            "calls": 0, "failures": 0, "cooldown_until": 0.0,
            "last_error": None, "last_latency_ms": None,
        })

    def available_keys(self) -> list[str]:
        now = time.time()
        return [key for key in self.api_keys if self.state_for(key)["cooldown_until"] <= now]

    def public(self) -> dict:
        now = time.time()
        keys = []
        for index, key in enumerate(self.api_keys):
            state = self.state_for(key)
            keys.append({
                "slot": index + 1,
                "masked": _mask_key(key),
                "cooldown_sec": max(0, int(state["cooldown_until"] - now)),
                "calls": state["calls"],
                "failures": state["failures"],
                "last_error": state["last_error"],
            })
        return {
            "name": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "priority": self.priority,
            "enabled": self.enabled,
            "json_mode": self.json_mode,
            "keys": len(self.api_keys),
            "available_keys": len(self.available_keys()),
            "calls": self.calls,
            "failures": self.failures,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "last_latency_ms": round(self.last_latency_ms, 1) if self.last_latency_ms is not None else None,
            "last_success_at": _iso_ts(self.last_success_at),
            "last_error": self.last_error,
            "key_slots": keys,
        }


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}…{key[-4:]}"


def _iso_ts(ts: float | None) -> str | None:
    if not ts:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "si", "sí")


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _keys_from_row(row: dict) -> list[str]:
    raw = row.get("api_keys") or row.get("keys") or row.get("api_key") or row.get("key") or ""
    if isinstance(raw, (list, tuple)):
        values = [str(item).strip() for item in raw]
    else:
        values = [part.strip() for part in str(raw).replace(";", ",").split(",")]
    return [value for value in values if value]


def _provider_from_row(row: dict) -> Provider | None:
    name = str(row.get("name") or row.get("id") or "").strip()
    base_url = str(row.get("base_url") or row.get("baseUrl") or "").strip().rstrip("/")
    model = str(row.get("model") or "").strip()
    keys = _keys_from_row(row)
    if not name or not base_url or not model or not keys:
        return None
    headers = row.get("extra_headers") or row.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}
    return Provider(
        name=name,
        base_url=base_url,
        model=model,
        api_keys=keys,
        priority=_as_int(row.get("priority"), 100),
        json_mode=_as_bool(row.get("json_mode"), True),
        enabled=_as_bool(row.get("enabled"), True),
        timeout=_as_float(row.get("timeout"), LLM_ROUTER_TIMEOUT),
        max_tokens=(_as_int(row.get("max_tokens"), 0) or None),
        extra_headers={str(k): str(v) for k, v in headers.items()},
    )


def _load_json_providers(path: str) -> list[Provider]:
    if not path:
        return []
    if not os.path.exists(path):
        log.warning("[llm_router] LLM_PROVIDERS_FILE no existe: %s", path)
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        rows = data.get("providers", []) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        return [provider for row in rows if isinstance(row, dict)
                for provider in [_provider_from_row(row)] if provider]
    except Exception as exc:
        log.error("[llm_router] error leyendo %s: %s", path, exc)
        return []


def _load_env_providers() -> list[Provider]:
    providers: list[Provider] = []
    # Proveedor legado (DeepSeek, etc.).
    if LLM_API_KEY and LLM_MODEL and LLM_BASE_URL:
        providers.append(Provider(
            name=os.getenv("LLM_PROVIDER_NAME", "deepseek").strip() or "deepseek",
            base_url=LLM_BASE_URL.rstrip("/"),
            model=LLM_MODEL,
            api_keys=[LLM_API_KEY],
            priority=_as_int(os.getenv("LLM_PRIORITY"), 100),
            json_mode=_as_bool(os.getenv("LLM_JSON_MODE"), True),
        ))
    # Proveedores numerados 1..20.
    for index in range(1, 21):
        prefix = f"LLM_PROVIDER_{index}_"
        name = os.getenv(prefix + "NAME", "").strip()
        if not name:
            continue
        base_url = os.getenv(prefix + "BASE_URL", "").strip().rstrip("/")
        model = os.getenv(prefix + "MODEL", "").strip()
        keys = _keys_from_row({
            "api_keys": os.getenv(prefix + "API_KEYS", "") or os.getenv(prefix + "API_KEY", "")
            or os.getenv(prefix + "KEYS", ""),
        })
        if not (base_url and model and keys):
            log.warning("[llm_router] proveedor %s incompleto (base_url/model/keys)", name)
            continue
        headers_raw = os.getenv(prefix + "HEADERS", "").strip()
        headers = {}
        if headers_raw:
            try:
                headers = json.loads(headers_raw)
            except Exception:
                log.warning("[llm_router] %s HEADERS no es JSON; se ignora", name)
        providers.append(Provider(
            name=name,
            base_url=base_url,
            model=model,
            api_keys=keys,
            priority=_as_int(os.getenv(prefix + "PRIORITY"), 100 + index),
            json_mode=_as_bool(os.getenv(prefix + "JSON_MODE"), True),
            enabled=_as_bool(os.getenv(prefix + "ENABLED"), True),
            timeout=_as_float(os.getenv(prefix + "TIMEOUT"), LLM_ROUTER_TIMEOUT),
            max_tokens=(_as_int(os.getenv(prefix + "MAX_TOKENS"), 0) or None),
            extra_headers={str(k): str(v) for k, v in (headers or {}).items()},
        ))
    return providers


def _merge_providers(providers: list[Provider]) -> list[Provider]:
    """Fusiona proveedores con el mismo nombre/base/model y suma sus claves."""
    merged: dict[tuple, Provider] = {}
    for provider in providers:
        key = (provider.name.lower(), provider.base_url.lower(), provider.model.lower())
        if key not in merged:
            merged[key] = provider
            continue
        current = merged[key]
        for api_key in provider.api_keys:
            if api_key not in current.api_keys:
                current.api_keys.append(api_key)
        current.priority = min(current.priority, provider.priority)
        current.enabled = current.enabled or provider.enabled
        current.json_mode = current.json_mode or provider.json_mode
        current.extra_headers.update(provider.extra_headers)
    return list(merged.values())


# ═══════════════════════════════════════════════════════════════
# Parseo robusto de JSON
# ═══════════════════════════════════════════════════════════════

def parse_json_object(content: str) -> dict | None:
    if not content:
        return None
    text = str(content).strip()
    # Quita fences ```json ... ```
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S | re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _error_text(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:300]


def _unsupported_param(exc: Exception, param: str) -> bool:
    text = _error_text(exc).lower()
    return param.lower() in text and any(
        token in text for token in ("unsupported", "not supported", "unknown", "invalid", "unexpected")
    )


# ═══════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════

class LLMRouter:
    def __init__(self):
        self.providers: list[Provider] = []
        self.clients: dict[tuple[str, str], OpenAI] = {}
        self.lock = threading.RLock()
        self.started_at = time.time()
        self.total_calls = 0
        self.reload(save=False)

    # ── configuración ──────────────────────────────────────────
    def reload(self, save: bool = True):
        providers = _load_json_providers(LLM_PROVIDERS_FILE)
        providers.extend(_load_env_providers())
        if not LLM_ROUTER_ENABLED:
            providers = [p for p in providers if p.priority >= 100][:1]
        providers = _merge_providers(providers)
        providers = [p for p in providers if p.enabled and p.api_keys]
        providers.sort(key=lambda p: (p.priority, p.name.lower()))
        with self.lock:
            self.providers = providers
            self.clients.clear()
            self._load_state()
        log.info("[llm_router] %s proveedor(es): %s", len(providers),
                 ", ".join(f"{p.name}:{p.model}" for p in providers) or "ninguno")
        if save:
            self._save_state()

    # ── estado persistido (sin claves) ─────────────────────────
    def _load_state(self):
        if not os.path.exists(LLM_ROUTER_STATE_FILE):
            return
        try:
            with open(LLM_ROUTER_STATE_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return
        rows = data.get("providers", {}) if isinstance(data, dict) else {}
        for provider in self.providers:
            row = rows.get(f"{provider.name}:{provider.model}") or {}
            if not isinstance(row, dict):
                continue
            provider.calls = _as_int(row.get("calls"), 0)
            provider.failures = _as_int(row.get("failures"), 0)
            provider.prompt_tokens = _as_int(row.get("prompt_tokens"), 0)
            provider.completion_tokens = _as_int(row.get("completion_tokens"), 0)
            provider.last_error = row.get("last_error")
            provider.last_latency_ms = row.get("last_latency_ms")

    def _save_state(self):
        with self.lock:
            payload = {
                "updated_at": _iso_ts(time.time()),
                "providers": {
                    f"{p.name}:{p.model}": {
                        "calls": p.calls,
                        "failures": p.failures,
                        "prompt_tokens": p.prompt_tokens,
                        "completion_tokens": p.completion_tokens,
                        "last_error": p.last_error,
                        "last_latency_ms": p.last_latency_ms,
                    }
                    for p in self.providers
                },
            }
        try:
            os.makedirs(os.path.dirname(LLM_ROUTER_STATE_FILE), exist_ok=True)
            tmp = LLM_ROUTER_STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, LLM_ROUTER_STATE_FILE)
        except Exception as exc:
            log.debug("[llm_router] no se pudo guardar estado: %s", exc)

    # ── selección de candidatos ────────────────────────────────
    def _candidates(self) -> list[tuple[Provider, str]]:
        candidates: list[tuple[Provider, str]] = []
        with self.lock:
            for provider in self.providers:
                keys = provider.available_keys()
                if not keys:
                    continue
                for key in keys:
                    candidates.append((provider, key))
        return candidates

    def _client(self, provider: Provider, key: str) -> OpenAI:
        cache_key = (provider.name, key)
        with self.lock:
            client = self.clients.get(cache_key)
            if client is None:
                client = OpenAI(
                    api_key=key,
                    base_url=provider.base_url,
                    timeout=provider.timeout,
                    default_headers=provider.extra_headers or None,
                )
                self.clients[cache_key] = client
            return client

    # ── llamada ────────────────────────────────────────────────
    def _call(self, provider: Provider, key: str, system_prompt: str,
              user_prompt: str) -> str:
        client = self._client(provider, key)
        kwargs: dict[str, Any] = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": LLM_TEMPERATURE,
        }
        if provider.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if provider.max_tokens:
            kwargs["max_tokens"] = provider.max_tokens

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Algunos modelos gratuitos no aceptan response_format o temperature.
            if "response_format" in kwargs and _unsupported_param(exc, "response_format"):
                kwargs.pop("response_format", None)
                try:
                    response = client.chat.completions.create(**kwargs)
                except Exception as exc2:
                    if "temperature" in kwargs and _unsupported_param(exc2, "temperature"):
                        kwargs.pop("temperature", None)
                        response = client.chat.completions.create(**kwargs)
                    else:
                        raise
            elif "temperature" in kwargs and _unsupported_param(exc, "temperature"):
                kwargs.pop("temperature", None)
                response = client.chat.completions.create(**kwargs)
            else:
                raise

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise ValueError("respuesta vacía del proveedor")
        usage = getattr(response, "usage", None)
        if usage:
            provider.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            provider.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        return content

    def _record_success(self, provider: Provider, key: str, latency_ms: float):
        state = provider.state_for(key)
        with self.lock:
            provider.calls += 1
            provider.last_latency_ms = latency_ms
            provider.last_success_at = time.time()
            provider.last_error = None
            state["calls"] += 1
            state["failures"] = 0
            state["last_latency_ms"] = latency_ms
            state["last_error"] = None
            self.total_calls += 1

    def _record_failure(self, provider: Provider, key: str, exc: Exception,
                        cooldown: float | None = None):
        state = provider.state_for(key)
        error = _error_text(exc)
        now = time.time()
        with self.lock:
            provider.failures += 1
            provider.last_error = error
            state["failures"] += 1
            state["last_error"] = error
            if cooldown:
                state["cooldown_until"] = now + cooldown

    # ── API pública ────────────────────────────────────────────
    def ask_json(self, system_prompt: str, user_prompt: str,
                 max_retries: int = 3) -> dict:
        candidates = self._candidates()
        if not candidates:
            log.error("[llm_router] sin proveedores disponibles (¿faltan claves o todos en cooldown?)")
            return {}

        attempts = min(max(1, LLM_ROUTER_MAX_ATTEMPTS), len(candidates))
        last_exc: Exception | None = None
        for provider, key in candidates[:attempts]:
            started = time.time()
            try:
                content = self._call(provider, key, system_prompt, user_prompt)
                data = parse_json_object(content)
                if data is None:
                    raise ValueError("JSON inválido en la respuesta")
                latency = (time.time() - started) * 1000
                self._record_success(provider, key, latency)
                log.info("[llm_router] %s/%s OK %.0f ms",
                         provider.name, provider.model, latency)
                data.setdefault("_llm_provider", provider.name)
                data.setdefault("_llm_model", provider.model)
                data.setdefault("_llm_latency_ms", round(latency, 1))
                self._save_state()
                return data
            except Exception as exc:
                last_exc = exc
                status = _status_code(exc)
                if status in (401, 403):
                    cooldown = 3600
                elif status == 429:
                    cooldown = max(120, LLM_ROUTER_COOLDOWN_SEC)
                elif status and status >= 500:
                    cooldown = LLM_ROUTER_COOLDOWN_SEC
                elif isinstance(exc, ValueError) and "JSON" in str(exc):
                    cooldown = 0
                else:
                    cooldown = LLM_ROUTER_COOLDOWN_SEC
                self._record_failure(provider, key, exc, cooldown=cooldown)
                log.warning("[llm_router] %s/%s falló: %s",
                            provider.name, provider.model, _error_text(exc)[:180])
                self._save_state()

        if last_exc:
            log.error("[llm_router] todos los intentos fallaron: %s", _error_text(last_exc)[:200])
        return {}

    def get_status(self) -> dict:
        with self.lock:
            providers = [p.public() for p in self.providers]
            return {
                "enabled": LLM_ROUTER_ENABLED,
                "provider_count": len(providers),
                "available_providers": sum(1 for p in providers if p["available_keys"] > 0 and p["enabled"]),
                "total_calls": sum(p["calls"] for p in providers),
                "prompt_tokens": sum(p["prompt_tokens"] for p in providers),
                "completion_tokens": sum(p["completion_tokens"] for p in providers),
                "providers": providers,
                "max_attempts": LLM_ROUTER_MAX_ATTEMPTS,
                "cooldown_sec": LLM_ROUTER_COOLDOWN_SEC,
                "started_at": _iso_ts(self.started_at),
            }


_router: LLMRouter | None = None
_router_lock = threading.Lock()


def get_router() -> LLMRouter:
    global _router
    with _router_lock:
        if _router is None:
            _router = LLMRouter()
        return _router


def get_status() -> dict:
    return get_router().get_status()


def reload_router() -> dict:
    get_router().reload()
    return get_router().get_status()
