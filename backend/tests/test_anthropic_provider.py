"""OFFLINE provider contract fixtures. No real Claude inference in this suite."""

import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.integration.anthropic_llm import AnthropicLLMProvider, convert
from app.integration.llm_provider import requested_provider
from app.integration.models import RunRequest
from app.integration.privacy import Redactor
from app.integration.scienceclaw.adapters.base import ToolUnavailable
from app.integration.scienceclaw.runtime.engine import CONCLUDE, Decision, function


def settings(**kw):
    return Settings(
        _env_file=None,
        anthropic_api_key=SecretStr("test-anthropic-key"),
        agent_llm_enabled=True,
        **kw,
    )


def install(monkeypatch, mode="success"):
    calls = []
    original = httpx.Client

    def handler(request):
        calls.append((request.url.path, json.loads(request.content) if request.content else {}))
        assert request.headers["x-api-key"] == "test-anthropic-key"
        if request.method == "GET":
            return httpx.Response(200, json={"id": "claude-haiku-5-5"})
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        if mode == "error":
            return httpx.Response(503, json={"error": {"message": "not persisted"}})
        payload = json.loads(request.content)
        name = payload["tools"][0]["name"]
        args = (
            {}
            if name != "conclude"
            else {
                "status": "completed",
                "rationale": "Synthetic audit fixture.",
                "evidence_hashes": ["a" * 64],
                "redesign_target": "none",
                "allowed_fragments": [],
            }
        )
        return httpx.Response(
            200,
            json={
                "model": "claude-haiku-5-5",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "tool_use", "id": "toolu_fixture", "name": name, "input": args}
                ],
                "usage": {"input_tokens": 100, "output_tokens": 30},
            },
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    return calls


def test_native_tool_and_conclude_contract_roundtrip(monkeypatch):
    calls = install(monkeypatch)
    provider = AnthropicLLMProvider(settings(), max_calls=2, max_cost_usd=0.02)
    messages = [
        {"role": "system", "content": "Offline fixture"},
        {"role": "user", "content": "Audit"},
    ]
    first = provider.chat(messages, [function("inspect_research", "Local audit")])
    assert first["provider"] == "anthropic"
    messages += [
        first["message"],
        {"role": "tool", "tool_name": "inspect_research", "content": '{"hash":"' + "a" * 64 + '"}'},
    ]
    final = provider.chat(messages, [CONCLUDE])
    parsed = Decision.parse(final["message"]["tool_calls"][0]["function"]["arguments"], {"a" * 64})
    assert parsed.evidence_hashes == ["a" * 64]
    payload = [p for path, p in calls if path == "/v1/messages"][-1]
    assert payload["messages"][-1]["content"][0]["type"] == "tool_result"
    assert payload["messages"][-1]["content"][0]["tool_use_id"] == "toolu_fixture"
    assert "temperature" not in payload
    assert provider.reserved_usd <= provider.budget
    with pytest.raises(ToolUnavailable, match="call limit"):
        provider.chat(messages, [CONCLUDE])
    assert sum(path == "/v1/messages" for path, _ in calls) == 2


def test_cost_gate_blocks_before_billable_post(monkeypatch):
    calls = install(monkeypatch)
    provider = AnthropicLLMProvider(settings(), max_cost_usd=0.000001)
    with pytest.raises(ToolUnavailable, match="dollar budget"):
        provider.chat(
            [{"role": "user", "content": "audit"}], [function("inspect_research", "audit")]
        )
    assert all(path != "/v1/messages" for path, _ in calls)
    assert provider.calls == 0


def test_failed_inference_is_never_retried(monkeypatch):
    calls = install(monkeypatch, "error")
    provider = AnthropicLLMProvider(settings(), max_calls=2)
    args = ([{"role": "user", "content": "audit"}], [function("inspect_research", "audit")])
    with pytest.raises(RuntimeError, match="503"):
        provider.chat(*args)
    with pytest.raises(ToolUnavailable, match="retry"):
        provider.chat(*args)
    assert sum(path == "/v1/messages" for path, _ in calls) == 1


def test_disabled_gate_never_contacts_claude(monkeypatch):
    calls = install(monkeypatch)
    provider = AnthropicLLMProvider(settings().model_copy(update={"agent_llm_enabled": False}))
    assert not provider.probe()["available"]
    with pytest.raises(ToolUnavailable):
        provider.chat([], [])
    assert calls == []


def test_provider_selection_preserves_explicit_nebius_and_preparation():
    config = settings()
    assert requested_provider(config, RunRequest(use_llm=True)) == "anthropic"
    assert requested_provider(config, RunRequest(use_nebius_llm=True)) == "nebius"
    assert requested_provider(config, RunRequest(workflow="preparation", use_llm=True)) is None
    assert requested_provider(config, RunRequest()) is None


def test_unmatched_tool_result_rejected_before_http():
    with pytest.raises(ValueError, match="outstanding"):
        convert([{"role": "tool", "tool_name": "invented", "content": "x"}], [])


def test_claude_credentials_and_headers_redacted():
    redactor = Redactor(settings())
    result = redactor(
        {
            "x-api-key": "test-anthropic-key",
            "note": "test-anthropic-key",
            "anthropic_api_key": "anything",
        }
    )
    assert result == {
        "x-api-key": "[redacted]",
        "note": "[redacted]",
        "anthropic_api_key": "[redacted]",
    }


def test_three_request_agent_allocation_reserves_last_for_conclusion(monkeypatch):
    from app.integration.scienceclaw.runtime.engine import READ

    calls = install(monkeypatch)
    provider = AnthropicLLMProvider(settings(anthropic_max_calls=24, anthropic_max_cost_usd=0.10))
    provider.begin_agent("A1")
    messages = [{"role": "user", "content": "Offline fixture; conclude."}]
    provider.chat(messages, [CONCLUDE])
    provider.chat(messages, [CONCLUDE])
    provider.chat(messages, [READ, CONCLUDE])
    assert [p for path, p in calls if path == "/v1/messages"][-1]["tools"][0]["name"] == "conclude"
    with pytest.raises(ToolUnavailable, match="allocation"):
        provider.chat(messages, [CONCLUDE])
    provider.begin_agent("A2")
    provider.chat(messages, [CONCLUDE])
    assert provider.agent_calls == {"A1": 3, "A2": 1}
    assert provider.calls == 4
