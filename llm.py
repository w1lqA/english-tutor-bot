import base64
import json
import logging
import re
from pathlib import Path

import aiohttp
from pydantic import ValidationError

import config
from vocabulary import VocabularyAnalysis

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "vocabulary.txt"


class LLMError(Exception):
    pass


async def analyze_vocabulary(text: str, images: list[bytes] | None = None) -> VocabularyAnalysis:
    """Send the post text (and optional JPEG images) to the LLM, return validated structure."""
    images = images or []
    system = PROMPT_PATH.read_text(encoding="utf-8")

    note = f"\n\n({len(images)} screenshot(s) attached)" if images else ""
    content: list[dict] = [{"type": "text", "text": f"Post text:\n{text}{note}"}]
    for img in images:
        b64 = base64.b64encode(img).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    raw = await _chat_json(system, content)
    try:
        return VocabularyAnalysis.model_validate(raw)
    except ValidationError as e:
        raise LLMError(f"LLM JSON did not match schema: {str(e)[:300]}") from e


async def _chat_json(system: str, user_content: list[dict]) -> dict:
    """Generic OpenAI-compatible chat call (works for Gemini, Groq, DeepSeek, ...)."""
    if not (config.LLM_API_KEY and config.LLM_BASE_URL and config.LLM_MODEL):
        raise LLMError("LLM_API_KEY / LLM_BASE_URL / LLM_MODEL not set in .env")

    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}

    try:
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers,
                                    proxy=config.PROXY_URL) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise LLMError(f"HTTP {resp.status}: {body[:300]}")
    except (aiohttp.ClientError, TimeoutError) as e:
        raise LLMError(f"Network error: {e!r}") from e

    try:
        content = json.loads(body)["choices"][0]["message"]["content"]
        content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content)  # strip fences if any
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise LLMError(f"Malformed LLM response: {body[:300]}") from e