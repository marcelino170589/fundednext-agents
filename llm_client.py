# llm_client.py
"""Cliente LLM con DeepSeek/Hermes-compatible."""
import json
import logging
from openai import OpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE

log = logging.getLogger("llm")
_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


def ask_json(system_prompt: str, user_prompt: str, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            resp = _client.chat.completions.create(
                model=LLM_MODEL,
                temperature=LLM_TEMPERATURE,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return json.loads(resp.choices[0].message.content)
        except json.JSONDecodeError as e:
            log.warning(f"JSON inválido ({attempt+1}): {e}")
        except Exception as e:
            log.warning(f"LLM error ({attempt+1}): {e}")
    return {}