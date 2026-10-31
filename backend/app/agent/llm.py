"""Minimal client for any OpenAI-compatible chat endpoint.

Implemented over httpx rather than a vendor SDK so the same code works against
OpenAI, a local server, or a gateway, by changing OPENAI_BASE_URL alone.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMNotConfiguredError(Exception):
    """No API key is set, so the candidate step cannot run."""


class LLMError(Exception):
    """The model endpoint failed or returned something unusable."""


async def complete_json(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    system: str,
    user: str,
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Ask the model for a single JSON object and return it parsed.

    Raises LLMNotConfiguredError when no key is set, LLMError on transport,
    status or parse failure.
    """
    if not settings.openai_api_key:
        raise LLMNotConfiguredError(
            "No LLM configured. Set OPENAI_API_KEY in backend/.env "
            "(and OPENAI_BASE_URL / LLM_MODEL if you are not using OpenAI)."
        )

    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,  # candidate selection should be near-reproducible
        "max_tokens": max_tokens,
    }
    try:
        response = await client.post(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            timeout=settings.llm_timeout_seconds,
        )
    except httpx.TransportError as exc:
        raise LLMError(f"Could not reach the model endpoint: {exc}") from exc

    if response.status_code >= 400:
        # Never echo the request back; it carries the key in a header.
        raise LLMError(
            f"Model endpoint returned HTTP {response.status_code}: {response.text[:300]}"
        )

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected response shape from the model endpoint: {exc}") from exc

    try:
        parsed = json.loads(content)
    except ValueError as exc:
        raise LLMError(f"Model did not return valid JSON: {content[:200]}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("Model returned JSON that is not an object.")
    return parsed
