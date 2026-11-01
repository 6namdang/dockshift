"""Ollama's documented native tool-calling API, restricted to local inference.

No downloads, cloud models, paid endpoints, or automatic credential discovery.
Reference: https://docs.ollama.com/capabilities/tool-calling
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol
from urllib.parse import urlparse

from ..adapters.base import ToolUnavailable


class LLMProvider(Protocol):
    """Provider-independent runtime boundary; no scientific calculations here."""

    def probe(self) -> dict: ...
    def chat(self, messages: list[dict], tools: list[dict]) -> dict: ...


class OllamaProvider:
    def __init__(self):
        self.base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        self.model = os.environ.get("SCIENCECLAW_LLM_MODEL", "scienceclaw-qwen3:4b")
        self.metadata = None

    def request(self, path, payload=None, timeout=5):
        parsed = urlparse(self.base)
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.scheme != "http":
            raise ToolUnavailable(
                "LOCAL_LLM_REQUIRED",
                "Only a loopback Ollama HTTP endpoint is enabled; paid inference has not been approved.",
            )
        req = urllib.request.Request(
            self.base + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        # Ignore HTTP proxy environment settings for loopback requests.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            req, timeout=timeout
        ) as r:
            return json.load(r)

    def probe(self):
        if not self.model:
            return {
                "available": False,
                "error_code": "LLM_NOT_CONFIGURED",
                "detail": "SCIENCECLAW_LLM_MODEL unset; no local LLM was selected. Install/start Ollama and configure an already downloaded tool-capable local model.",
                "model": None,
            }
        try:
            if "cloud" in self.model.lower() or "/" in self.model:
                raise ValueError("cloud or remote model names are disabled")
            tags = self.request("/api/tags")
            if self.model not in {m["name"] for m in tags.get("models", [])}:
                raise ValueError(
                    "selected model is not already installed; automatic downloads are disabled"
                )
            meta = self.request("/api/show", {"model": self.model})
            if meta.get("remote_host") or meta.get("remote_model"):
                raise ValueError("remote/cloud-backed models are disabled")
            if "tools" not in meta.get("capabilities", []):
                raise ValueError("model does not advertise tool calling")
            self.metadata = meta
            return {
                "available": True,
                "model": self.model,
                "provider": "ollama",
                "provider_version": self.request("/api/version").get("version"),
                "model_digest": next(
                    m.get("digest") for m in tags["models"] if m["name"] == self.model
                ),
            }
        except Exception as exc:
            return {
                "available": False,
                "model": self.model,
                "error_code": "LOCAL_LLM_UNAVAILABLE",
                "detail": str(exc),
            }

    def chat(self, messages, tools):
        return self.request(
            "/api/chat",
            {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.8,
                    "top_k": 20,
                    "seed": 42,
                    "num_ctx": 8192,
                    "num_predict": 1536,
                },
            },
            timeout=180,
        )
