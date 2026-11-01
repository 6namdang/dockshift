"""Nebius Token Factory binding for the source runtime's provider interface."""

import json
from urllib.parse import urlparse

import httpx

from .scienceclaw.adapters.base import ToolUnavailable


class NebiusLLMProvider:
    def __init__(self, settings, max_calls=64):
        self.settings = settings
        self.base = settings.nebius_llm_base_url.rstrip("/")
        self.model = settings.nebius_llm_model
        self._discovery = None
        self.max_calls, self.calls = max_calls, 0

    def probe(self):
        host = urlparse(self.base)
        available = bool(
            self.settings.agent_llm_enabled and self.model and self.settings.nebius_llm_api_key
        )
        available = (
            available
            and host.scheme == "https"
            and bool(host.hostname and host.hostname.endswith(".nebius.com"))
        )
        if not available:
            return {
                "available": False,
                "model": self.model,
                "provider": "nebius",
                "detail": "Nebius agent inference requires AGENT_LLM_ENABLED, "
                "NEBIUS_LLM_MODEL and NEBIUS_LLM_API_KEY at a Nebius HTTPS endpoint.",
            }
        if self._discovery is None:
            try:
                with httpx.Client(timeout=15, follow_redirects=False) as client:
                    response = client.get(
                        self.base + "/models",
                        headers={
                            "Authorization": "Bearer "
                            + self.settings.nebius_llm_api_key.get_secret_value(),
                        },
                    )
                    response.raise_for_status()
                    names = {row["id"] for row in response.json()["data"]}
                self._discovery = {
                    "available": self.model in names,
                    "model": self.model,
                    "provider": "nebius",
                    "catalog_verified": True,
                    "detail": None
                    if self.model in names
                    else "Selected Nebius model is absent from the authenticated catalog.",
                }
            except Exception:
                self._discovery = {
                    "available": False,
                    "model": self.model,
                    "provider": "nebius",
                    "catalog_verified": False,
                    "detail": "Nebius model catalog could not be authenticated.",
                }
        return self._discovery

    def chat(self, messages, tools):
        if not self.probe()["available"]:
            raise ToolUnavailable("NEBIUS_LLM_REQUIRED", self.probe()["detail"])
        if self.calls >= self.max_calls:
            raise ToolUnavailable("LLM_BUDGET_EXHAUSTED", "No authorized LLM calls remain.")
        converted, outstanding = [], []
        for i, source in enumerate(messages):
            message = dict(source)
            if message["role"] == "assistant" and message.get("tool_calls"):
                calls = []
                for j, call in enumerate(message["tool_calls"]):
                    function = dict(call["function"])
                    if not isinstance(function.get("arguments"), str):
                        function["arguments"] = json.dumps(function.get("arguments", {}))
                    call_id = call.get("id") or f"call_{i}_{j}"
                    calls.append({"id": call_id, "type": "function", "function": function})
                    outstanding.append((function["name"], call_id))
                message["tool_calls"] = calls
            if message["role"] == "tool":
                name = message.pop("tool_name", None)
                match = next((v for v in outstanding if v[0] == name), None)
                if not match:
                    raise ValueError("Tool response has no matching inference call")
                outstanding.remove(match)
                message["tool_call_id"] = match[1]
            converted.append(message)
        self.calls += 1
        with httpx.Client(
            timeout=self.settings.llm_timeout_seconds, follow_redirects=False
        ) as client:
            response = client.post(
                self.base + "/chat/completions",
                headers={
                    "Authorization": "Bearer "
                    + self.settings.nebius_llm_api_key.get_secret_value(),
                },
                json={
                    "model": self.model,
                    "messages": converted,
                    "tools": tools,
                    "temperature": 0,
                    "max_tokens": 800,
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Nebius inference returned HTTP {response.status_code}")
        data = response.json()
        return {
            "model": data.get("model", self.model),
            "message": data["choices"][0]["message"],
            "usage": data.get("usage"),
            "provider": "nebius",
        }
