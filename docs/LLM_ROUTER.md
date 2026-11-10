# Router multi-LLM: usar varios proveedores y ahorrar tokens

> La lista [mnfst/awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis)
> **no es una librería instalable**: es un catálogo de APIs con free tier.
> Este proyecto la convierte en una cadena de proveedores OpenAI-compatible
> mediante `llm_router.py`.

## Qué hace el router

`llm_client.ask_json()` ahora pasa por `llm_router.py`:

1. Ordena los proveedores por `priority` (menor = primero).
2. Rota las claves de cada proveedor.
3. Si un proveedor devuelve 429, 5xx, timeout, 401/403 o JSON inválido, lo
   pone en cooldown y prueba el siguiente.
4. Parsea JSON aunque venga con ```json ... ``` o texto alrededor.
5. Cuenta llamadas y tokens de entrada/salida por proveedor.
6. Nunca escribe las claves en logs ni en el estado persistido.

El estado se puede ver en:

```bash
curl http://127.0.0.1:8000/api/llm/status
```

Y en el dashboard: **Sistema → Proveedores LLM**.

## Configuración rápida con `.env`

El proveedor legado (`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`) sigue
funcionando como fallback. Para añadir proveedores gratuitos delante:

```env
LLM_ROUTER_ENABLED=true
LLM_ROUTER_MAX_ATTEMPTS=6
LLM_ROUTER_COOLDOWN_SEC=90

# 1) Groq (free tier)
LLM_PROVIDER_1_NAME=groq
LLM_PROVIDER_1_BASE_URL=https://api.groq.com/openai/v1
LLM_PROVIDER_1_MODEL=openai/gpt-oss-20b
LLM_PROVIDER_1_API_KEYS=clave1,clave2
LLM_PROVIDER_1_PRIORITY=10
LLM_PROVIDER_1_JSON_MODE=true

# 2) Google Gemini (free tier)
LLM_PROVIDER_2_NAME=gemini
LLM_PROVIDER_2_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_PROVIDER_2_MODEL=gemini-2.5-flash
LLM_PROVIDER_2_API_KEY=clave3
LLM_PROVIDER_2_PRIORITY=20

# 3) Mistral AI (free mode)
LLM_PROVIDER_3_NAME=mistral
LLM_PROVIDER_3_BASE_URL=https://api.mistral.ai/v1
LLM_PROVIDER_3_MODEL=mistral-small-latest
LLM_PROVIDER_3_API_KEY=clave4
LLM_PROVIDER_3_PRIORITY=30

# 4) OpenRouter free (modelos con sufijo :free)
LLM_PROVIDER_4_NAME=openrouter
LLM_PROVIDER_4_BASE_URL=https://openrouter.ai/api/v1
LLM_PROVIDER_4_MODEL=google/gemma-4-31b-it:free
LLM_PROVIDER_4_API_KEY=clave5
LLM_PROVIDER_4_PRIORITY=40
```

El proveedor legado de DeepSeek queda con prioridad 100; si los gratuitos
fallan, se usa DeepSeek.

### Varias claves por proveedor

```env
LLM_PROVIDER_1_API_KEYS=claveA,claveB,claveC
```

El router reparte las llamadas y pone en cooldown solo la clave que falla.
`claveA,claveB` también se puede escribir como lista en el JSON.

### Formato JSON alternativo

`LLM_PROVIDERS_FILE=/ruta/llm_providers.json`:

```json
{
  "providers": [
    {
      "name": "groq",
      "base_url": "https://api.groq.com/openai/v1",
      "model": "openai/gpt-oss-20b",
      "api_keys": ["clave1", "clave2"],
      "priority": 10,
      "json_mode": true
    }
  ]
}
```

Mantén ese archivo fuera de git y con permisos `600`.

## Proveedores del catálogo que puedes usar

La lista completa está en
[awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis).
Ejemplos con endpoint OpenAI-compatible:

| Proveedor | Base URL | Modelo de ejemplo | Nota |
|---|---|---|---|
| Groq | `https://api.groq.com/openai/v1` | `openai/gpt-oss-20b` | Muy rápido, 1.000 RPD. |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.5-flash` | Free tier; puede usar prompts para mejorar. |
| Mistral | `https://api.mistral.ai/v1` | `mistral-small-latest` | Free mode; revisa entrenamiento. |
| Cohere | `https://api.cohere.ai/compatibility/v1` | `command-r` | Free trial no comercial. |
| OpenRouter | `https://openrouter.ai/api/v1` | `google/gemma-4-31b-it:free` | 50 RPD en modelos `:free`. |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `openai/gpt-oss-20b` | Requiere Developer Program. |
| Cloudflare Workers AI | `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | 10K neurons/día. |
| LLM7.io | `https://api.llm7.io/v1` | `gpt-oss:20b` | Free token opcional. |
| OVHcloud | `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1` | `gpt-oss-20b` | 2 RPM anónimo, sin clave. |
| Meta Model API | `https://api.meta.ai/v1` | `muse-spark-1.3` | **Pago**, no usa los 100M de Muse. |

### Si el proveedor no acepta `response_format`

Pon:

```env
LLM_PROVIDER_1_JSON_MODE=false
```

El router igualmente intenta extraer el JSON de la respuesta. Si el modelo
devuelve texto sin JSON, se considera fallo y pasa al siguiente proveedor.

## Sobre Meta Muse y los 100M tokens semanales

Hay que separar dos cosas:

1. **Muse (app/agente de Meta)**: según Meta y la prensa, la app Muse ofrece
   **100 millones de tokens por semana** en su plan gratuito. Es una cuota de
   uso **dentro de la app/agente Muse**, no una API pública para que otra
   aplicación consuma esos tokens.
2. **Meta Model API**: es la API para desarrolladores de los modelos Muse
   Spark. Es **OpenAI-compatible**, base `https://api.meta.ai/v1`, modelo
   `muse-spark-1.3` (o `1.1`). Su precio público es aproximadamente
   **$1.25 / 1M tokens de entrada** y **$4.25 / 1M de salida**; el modelo
   `-contributor` tiene precio reducido a cambio de permitir entrenamiento con
   tus prompts.

Por tanto:

- **No hay una forma legítima de conectar los 100M gratuitos de Muse a este
  proyecto**: no es una API documentada para terceros.
- Si tienes una **clave de Meta Model API**, sí puedes añadirla al router:

```env
LLM_PROVIDER_9_NAME=meta
LLM_PROVIDER_9_BASE_URL=https://api.meta.ai/v1
LLM_PROVIDER_9_MODEL=muse-spark-1.3
LLM_PROVIDER_9_API_KEY=tu_model_api_key
LLM_PROVIDER_9_PRIORITY=90
LLM_PROVIDER_9_MAX_TOKENS=4096
```

- No automatices la app Muse ni extraigas su sesión para usar la cuota: rompe
  sus términos y no es estable.

Referencias:

- [Meta Model API: Muse Spark](https://dev.meta.ai/resources/blog/build-with-muse-spark)
- [Promptfoo: Meta Model API](https://www.promptfoo.dev/docs/providers/meta/)
- [Gizmodo: Muse y los 100M de tokens semanales](https://gizmodo.com/metas-muse-let-me-waste-a-mind-boggling-amount-of-free-compute-on-nothing-in-particular-2000808945)
- [OrcaRouter: qué es la API de Muse](https://www.orcarouter.ai/blog/muse-api)

## Cómo ahorrar de verdad

1. **Prioriza gratuitos** (`priority` 10–40) y deja el de pago en 100.
2. **Limita intentos** con `LLM_ROUTER_MAX_ATTEMPTS=4`; cada intento cuesta.
3. **No mandes el mismo contexto** a todos los agentes: el fundamental ya
   cachea titulares; el cazador cachea el macro 1 hora.
4. **Baja el contexto**: recorta titulares/eventos a lo esencial.
5. **Usa modelos pequeños** para tareas simples (clasificar, resumir) y uno
   mejor solo para el consenso final.
6. **Cachea respuestas** si repites el mismo prompt (no implementado aún).
7. **Mide tokens** en `/api/llm/status` y ajusta prioridades.
8. **Evita reintentos dobles**: el router ya cambia de proveedor; no envuelvas
   otra capa de reintentos infinitos.

## Seguridad y términos

- Los free tiers suelen **usar prompts para entrenar** o limitar el uso
  comercial. Revisa los términos de cada proveedor antes de enviar datos de
  cuentas, clientes o estrategias.
- No pongas claves en `README`, capturas, Telegram ni en el frontend.
- Mantén `.env` y `llm_providers.json` fuera de git.
- Para un producto que cobras, prefiere proveedores con acuerdo de datos y
  facturación; los free tiers no son una base estable de SLA.
- El router no cambia la lógica de trading: solo el proveedor que responde.
