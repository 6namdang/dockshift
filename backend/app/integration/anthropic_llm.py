"""Claude Messages adapter for the existing runtime, with bounded client-tool use.

No scientific engines or server-side paid tools are exposed. Never retries a
billable request. Dollar admission uses conservative token reservations and the
published short-context Haiku 5.5 rates, with counting/serialization headroom.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
from jsonschema import Draft202012Validator

from .scienceclaw.adapters.base import ToolUnavailable

API = "https://api.anthropic.com/v1"
# USD / million tokens. Config limits inputs to <=50K, below the 100K price tier.
RATES = {
    "claude-haiku-5-5": (Decimal(".10"), Decimal(".50")),
    "claude-haiku-4-5-20251001": (Decimal("1"), Decimal("5")),
}


def convert(messages, tools):
    system, converted, outstanding = [], [], {}
    for index, source in enumerate(messages):
        role = source["role"]
        if role == "system":
            system.append(source.get("content", ""))
            continue
        if role == "assistant":
            blocks = []
            if source.get("content"):
                blocks.append({"type": "text", "text": source["content"]})
            for j, call in enumerate(source.get("tool_calls", [])):
                function = call["function"]
                args = function.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)
                call_id = call.get("id") or f"call_{index}_{j}"
                outstanding[call_id] = function["name"]
                blocks.append(
                    {"type": "tool_use", "id": call_id, "name": function["name"], "input": args}
                )
            # This provider forces client tool use and does not request thinking.
            # Preserve native blocks if a future verified model returns them.
            blocks = source.get("anthropic_content") or blocks
            converted.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            call_id = source.get("tool_call_id")
            if not call_id:
                call_id = next(
                    (k for k, v in outstanding.items() if v == source.get("tool_name")), None
                )
            if call_id not in outstanding:
                raise ValueError("Tool response has no outstanding Claude tool-use block")
            outstanding.pop(call_id)
            block = {"type": "tool_result", "tool_use_id": call_id, "content": source["content"]}
            if converted and converted[-1]["role"] == "user":
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
        elif role == "user":
            converted.append(
                {"role": "user", "content": [{"type": "text", "text": source["content"]}]}
            )
        else:
            raise ValueError("Unsupported runtime message role")
    native_tools = [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": t["function"]["parameters"],
            "strict": True,
        }
        for t in tools
    ]
    return {"system": "\n\n".join(system), "messages": converted, "tools": native_tools}


class AnthropicLLMProvider:
    def __init__(self, settings, max_calls=None, max_cost_usd=None):
        self.settings = settings
        self.model = settings.anthropic_model
        self.max_calls = min(
            settings.anthropic_max_calls,
            max_calls if max_calls is not None else settings.anthropic_max_calls,
        )
        self.budget = Decimal(
            str(
                min(
                    settings.anthropic_max_cost_usd,
                    max_cost_usd if max_cost_usd is not None else settings.anthropic_max_cost_usd,
                )
            )
        )
        self.calls = 0
        self.failed = False
        self.reserved_usd = Decimal(0)
        self.usage = []
        self._discovery = None
        self.agent_calls = {}
        self.active_agent = None

    def begin_agent(self, agent):
        self.active_agent = agent
        self.agent_calls.setdefault(agent, 0)

    def headers(self):
        return {
            "x-api-key": self.settings.anthropic_api_key.get_secret_value(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def probe(self):
        if not self.settings.agent_llm_enabled or not self.settings.anthropic_api_key:
            return {
                "available": False,
                "provider": "anthropic",
                "model": self.model,
                "detail": "Claude requires ANTHROPIC_API_KEY and AGENT_LLM_ENABLED.",
            }
        if self.model not in RATES:
            return {
                "available": False,
                "provider": "anthropic",
                "model": self.model,
                "detail": "Selected Claude model has no reviewed cost profile; no fallback used.",
            }
        if self._discovery is None:
            try:
                with httpx.Client(timeout=15, follow_redirects=False) as client:
                    response = client.get(API + "/models/" + self.model, headers=self.headers())
                    response.raise_for_status()
                    available = response.json().get("id") == self.model
                self._discovery = {
                    "available": available,
                    "provider": "anthropic",
                    "model": self.model,
                    "catalog_verified": available,
                    "detail": None if available else "Claude model ID not verified.",
                }
            except (httpx.HTTPError, ValueError):
                self._discovery = {
                    "available": False,
                    "provider": "anthropic",
                    "model": self.model,
                    "detail": (
                        "Claude model catalog could not be authenticated; credentials withheld."
                    ),
                }
        return self._discovery

    def chat(self, messages, tools):
        if self.active_agent:
            if self.agent_calls[self.active_agent] >= 3:
                raise ToolUnavailable("AGENT_CALL_LIMIT", "Three-request agent allocation reached.")
            if self.agent_calls[self.active_agent] >= 2:
                tools = [t for t in tools if t["function"]["name"] == "conclude"]
                if not tools:
                    raise ToolUnavailable("AGENT_CALL_LIMIT", "Final agent request must conclude.")
        if self.active_agent and any(t["function"]["name"] == "conclude" for t in tools):
            # Demo tool summaries are already bounded and evidence-linked. Finish the
            # actual decision instead of spending more calls on optional reads.
            tools = [t for t in tools if t["function"]["name"] == "conclude"]
        if self.failed:
            raise ToolUnavailable(
                "CLAUDE_ATTEMPT_FAILED", "Prior inference failed; no automatic retry permitted."
            )
        if self.calls >= self.max_calls:
            raise ToolUnavailable("LLM_BUDGET_EXHAUSTED", "Claude inference-call limit reached.")
        if not self.probe()["available"]:
            raise ToolUnavailable("CLAUDE_NOT_AVAILABLE", self.probe()["detail"])
        payload = {
            "model": self.model,
            **convert(messages, tools),
            "max_tokens": self.settings.anthropic_max_output_tokens,
            "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
        }
        # Count before every billable request; no automatic SDK/HTTP retries.
        count_payload = {k: v for k, v in payload.items() if k not in ("max_tokens",)}
        with httpx.Client(
            timeout=self.settings.llm_timeout_seconds, follow_redirects=False
        ) as client:
            counted = client.post(
                API + "/messages/count_tokens", headers=self.headers(), json=count_payload
            )
            if counted.status_code != 200:
                raise ToolUnavailable(
                    "CLAUDE_TOKEN_COUNT_FAILED",
                    "Claude input counting failed; no inference submitted.",
                )
            count = counted.json().get("input_tokens")
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise ValueError("Invalid Claude token count")
            upper = max(
                count * 2 + 1024, len(json.dumps(payload, ensure_ascii=False).encode()) + 1024
            )
            if upper > self.settings.anthropic_max_input_tokens:
                raise ToolUnavailable(
                    "CLAUDE_CONTEXT_BUDGET", "Claude request exceeds the conservative input limit."
                )
            rate_in, rate_out = RATES[self.model]
            reserved = (
                Decimal(upper) * rate_in + Decimal(payload["max_tokens"]) * rate_out
            ) / Decimal(1_000_000)
            if self.reserved_usd + reserved > self.budget:
                raise ToolUnavailable(
                    "LLM_COST_BUDGET_EXHAUSTED",
                    "Claude request exceeds the remaining dollar budget.",
                )
            # Failed/ambiguous requests retain their reservation and consume a call.
            self.reserved_usd += reserved
            self.calls += 1
            if self.active_agent:
                self.agent_calls[self.active_agent] += 1
            self.failed = True
            response = client.post(API + "/messages", headers=self.headers(), json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Claude inference returned HTTP {response.status_code}; no retry performed."
            )
        data = response.json()
        if data.get("model") != self.model or data.get("stop_reason") != "tool_use":
            raise ValueError("Claude returned no complete tool call for the selected model")
        available = {t["name"]: t["input_schema"] for t in payload["tools"]}
        calls = []
        for block in data.get("content", []):
            if block.get("type") != "tool_use":
                continue
            if block["name"] not in available:
                raise ValueError("Claude selected an unadvertised tool")
            Draft202012Validator(available[block["name"]]).validate(block["input"])
            calls.append(
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {"name": block["name"], "arguments": block["input"]},
                }
            )
        if len(calls) != 1:
            raise ValueError("Exactly one bounded client-tool call required")
        usage = data.get("usage", {})
        self.usage.append(usage)
        self.failed = False
        return {
            "provider": "anthropic",
            "model": data["model"],
            "usage": usage,
            "request_id": response.headers.get("request-id"),
            "cost_reservation_usd": str(reserved),
            "reserved_total_usd": str(self.reserved_usd),
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": calls,
                "anthropic_content": data["content"],
            },
        }
