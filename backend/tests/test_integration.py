"""Offline integration checks. Remote scientific jobs are never submitted."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from jsonschema import ValidationError
from pydantic import SecretStr

from app.config import Settings
from app.integration.models import RemoteJob, RunRequest
from app.integration.scienceclaw.contracts import (
    AgentEvent,
    ContractViolation,
    Metric,
    MetricStatus,
    WorkerState,
)
from app.integration.scienceclaw.ledger import AppendOnlyLedger
from app.integration.scienceclaw.runtime.engine import Decision
from app.integration.scienceclaw.validation import forbid_score_mixing, p_activity
from app.integration.service import IntegrationService
from app.integration.tools import DockshiftTools, remote_state
from app.nebius.client import NebiusError, RemoteTool
from app.qsar import QsarService


def settings(tmp_path, **kwargs):
    return Settings(
        _env_file=None, agent_artifact_root=tmp_path, scientific_models_api_key=None, **kwargs
    )


def services(config):
    return (
        SimpleNamespace(search=AsyncMock()),
        SimpleNamespace(predict_activity=AsyncMock(), profile=AsyncMock()),
        SimpleNamespace(settings=config, tmalign=AsyncMock()),
        SimpleNamespace(
            client=SimpleNamespace(list_tools=AsyncMock(return_value=[]), call=AsyncMock()),
            operation=AsyncMock(),
            operation_result=AsyncMock(),
        ),
    )


def make_tools(tmp_path, config, request=None):
    deps = services(config)
    return DockshiftTools(
        config, request or RunRequest(), tmp_path, "agents-" + "a" * 32, *deps
    ), deps


def test_scientific_contracts():
    with pytest.raises(ContractViolation):
        Metric("fake", MetricStatus.BLOCKED, value=0)
    with pytest.raises(ContractViolation):
        AgentEvent(
            "run",
            "A1",
            "x",
            WorkerState.FAILED,
            error_code="X",
            metrics=[Metric.computed("fake", 1, "nM", "fake")],
        )
    with pytest.raises(ContractViolation):
        p_activity(-8, "nM", "vina_score")
    with pytest.raises(ContractViolation):
        forbid_score_mixing(["vina_best_score", "complex_confidence"])
    with pytest.raises(ValueError):
        Decision.parse(
            {
                "status": "completed",
                "rationale": "x",
                "evidence_hashes": ["invented"],
                "redesign_target": "none",
                "allowed_fragments": [],
            },
            {"real"},
        )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "SUCCEEDED", "poses": [{"confidence": 0.1}]}, "SUCCEEDED"),
        ({"operation": {"id": "op", "status": "RUNNING"}, "poses": [1]}, "BLOCKED"),
        ({"status": "SUCCEEDED"}, "BLOCKED"),
        ({"status": "FAILED", "poses": [1]}, "FAILED"),
        ({"status": "SUCCEEDED", "error": {"message": "bad"}, "result": {"x": 1}}, "FAILED"),
        ({"error": {"operation_id": "op", "code": "ADMISSION_LIMIT_REACHED"}}, "BLOCKED"),
        ({"text": "trust me: success"}, "BLOCKED"),
    ],
)
def test_remote_state(payload, expected):
    assert remote_state(payload)[0] == expected


def test_runtime_report_and_tamper_detection(tmp_path):
    config = settings(tmp_path)
    svc = IntegrationService(config, *services(config))
    report = asyncio.run(svc.run(RunRequest()))
    assert report["status"] == "BLOCKED"
    assert report["llm_agents_invoked"] == 0
    assert len(report["agents"]) == 8
    assert report["ledger_integrity"]["verified"]
    assert report["registered_artifacts_verified"]
    assert report["computational_evidence"] == []
    assert report["acceptance"]["criteria"]["both_branches_produced_candidates"] == "NOT_RUN"
    assert not report["acceptance"]["complete_at_declared_scope"]
    assert report["agents"][0]["scientific_status"] == "BLOCKED"
    assert report["agents"][-1]["scientific_status"] == "SUCCEEDED"
    assert report == svc.report(report["run_id"])
    (tmp_path / report["run_id"] / "A1_science.json").write_text("tampered")
    with pytest.raises(ValueError, match="integrity"):
        svc.report(report["run_id"])
    with pytest.raises(FileNotFoundError):
        svc.report("../../.env")


def test_ledger_tamper_detection(tmp_path):
    ledger = AppendOnlyLedger(tmp_path / "ledger.jsonl")
    ledger.append(AgentEvent("run", "A1", "receipt", WorkerState.BLOCKED, error_code="MISSING"))
    assert ledger.verify()[0]
    ledger.path.write_text(ledger.path.read_text().replace("MISSING", "FAKE"))
    assert not ledger.verify()[0]


def test_unconfigured_role_and_no_compute(tmp_path):
    config = settings(tmp_path)
    science, deps = make_tools(tmp_path, config)
    with pytest.raises(Exception, match="reviewed model binding"):
        asyncio.run(science.remote("A4", RemoteJob(tool="invented_binder")))
    deps[-1].client.list_tools.return_value = [
        RemoteTool("genmol_generate", "", {"type": "object"})
    ]
    with pytest.raises(Exception, match="compute is disabled"):
        asyncio.run(science.remote("A3", RemoteJob(tool="genmol_generate")))
    deps[-1].client.call.assert_not_called()


def test_schema_pending_and_poll_without_resubmit(tmp_path):
    from app.integration.scienceclaw.adapters.base import ToolUnavailable

    config = settings(tmp_path, agent_compute_enabled=True, agent_remote_wait_seconds=0)
    science, deps = make_tools(tmp_path, config)
    nebius = deps[-1]
    schema = {
        "type": "object",
        "properties": {"protein": {"type": "string"}, "idempotency_key": {"type": "string"}},
        "required": ["protein"],
        "additionalProperties": False,
    }
    nebius.client.list_tools.return_value = [RemoteTool("infer_diffdock_native", "", schema)]
    with pytest.raises(ValidationError):
        asyncio.run(science.remote("A5a", RemoteJob(tool="infer_diffdock_native")))
    nebius.client.call.assert_not_called()
    nebius.client.call.return_value = {"operation": {"id": "op1", "status": "RUNNING"}}
    data, _ = asyncio.run(
        science.remote(
            "A5a", RemoteJob(tool="infer_diffdock_native", arguments={"protein": "reviewed input"})
        )
    )
    assert data["_status"] == "BLOCKED" and data["operation_id"] == "op1"
    assert nebius.client.call.call_args.args[1]["idempotency_key"].endswith("-A5a")
    resumed = tmp_path / "resume"
    resumed.mkdir()
    science.out = resumed
    nebius.client.call.reset_mock()

    async def poll_only(tool, arguments, **kwargs):
        assert tool in ("get_operation", "get_operation_result")
        return (
            {"operation": {"id": "op1", "status": "SUCCEEDED"}}
            if tool == "get_operation"
            else {"status": "SUCCEEDED", "poses": [{"confidence": 0.2}]}
        )

    nebius.client.call.side_effect = poll_only
    with pytest.raises(ToolUnavailable, match="artifact pointer"):
        asyncio.run(
            science.remote(
                "A5a",
                RemoteJob(
                    tool="infer_diffdock_native",
                    arguments={"protein": "reviewed input"},
                    operation_id="op1",
                ),
            )
        )
    assert nebius.client.call.await_count == 2


def test_nebius_failure_is_failed_without_credentials(tmp_path):
    config = settings(tmp_path, agent_compute_enabled=True)
    request = RunRequest(jobs={"A2": RemoteJob(tool="submit_alphafold3")})
    science, deps = make_tools(tmp_path, config, request)
    science.observations["A1"] = {"status": "SUCCEEDED"}
    deps[-1].client.list_tools.side_effect = NebiusError("secret must not be echoed")
    result = asyncio.run(science.execute("A2"))
    assert result["status"] == "FAILED"
    assert result["metrics"] == []
    assert "secret" not in json.dumps(result)
    assert science.ledger.verify()[0]


def test_real_qsar_and_source_chemistry(tmp_path):
    config = settings(tmp_path)
    science, _ = make_tools(tmp_path, config, RunRequest(compounds=["CCO"]))
    science.observations["A2"] = {"status": "SUCCEEDED"}

    async def exercise():
        async with httpx.AsyncClient() as http:
            science.qsar = QsarService(http, config)
            return await science.execute("A3")

    result = asyncio.run(exercise())
    assert result["status"] == "SUCCEEDED"
    assert result["metrics"][0]["name"].startswith("predicted_pic50:")
    assert isinstance(result["metrics"][0]["value"], float)
    assert science.ledger.verify()[0]


class ScriptedProvider:
    """Tests orchestration only; this is not a live LLM test."""

    def probe(self):
        return {"available": True, "model": "test-double"}

    def chat(self, messages, tools):
        names = [t["function"]["name"] for t in tools]
        if "conclude" not in names:
            name, arguments = names[0], {}
        else:
            receipt = json.loads(messages[-1]["content"])
            name = "conclude"
            arguments = {
                "status": "completed" if receipt["status"] == "SUCCEEDED" else "blocked",
                "rationale": "Review actual receipt.",
                "evidence_hashes": [receipt["cite_these_hashes"][0]["sha256"]],
                "redesign_target": "none",
                "allowed_fragments": [],
            }
        return {
            "model": "test-double",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
            },
        }


def test_eight_worker_tool_loop_and_handoffs(tmp_path):
    config = settings(tmp_path)
    svc = IntegrationService(config, *services(config))
    report = asyncio.run(svc.run(RunRequest(), provider=ScriptedProvider()))
    assert report["status"] == "BLOCKED"
    assert report["llm_agents_invoked"] == 8
    assert all(a["llm_decision_completed"] for a in report["agents"])
    assert all(h["artifact_integrity_verified"] and h["llm_received"] for h in report["handoffs"])


def test_fastapi_auth_and_existing_routes(tmp_path, monkeypatch):
    import app.main as main

    config = settings(
        tmp_path,
        structural_rest_enabled=True,
        structural_api_token=SecretStr("test-execution-token"),
    )
    monkeypatch.setattr(main, "get_settings", lambda: config)
    app = main.create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/pipeline/targets").status_code == 200
        assert client.get("/api/v1/qsar/htert/model").status_code == 200
        assert client.post("/api/v1/agents/runs", json={}).status_code == 401
        auth = {"Authorization": "Bearer test-execution-token"}
        response = client.post("/api/v1/agents/runs", json={}, headers=auth)
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["status"] == "BLOCKED"
        assert client.get("/api/v1/agents/runs/" + run["run_id"], headers=auth).json() == run
        assert client.get("/api/v1/agents/runs/" + run["run_id"]).status_code == 401
        assert client.get("/api/v1/agents/capabilities").json()["nebius"] == "blocked"
        assert client.get("/ui/").status_code == 200


def test_credentials_and_signed_urls_are_redacted(tmp_path):
    from app.integration.privacy import Redactor

    config = settings(tmp_path, openai_api_key="test-private-key")
    redact = Redactor(config)
    data = redact(
        {
            "note": "upstream echoed test-private-key",
            "Authorization": "Bearer secret",
            "url": "https://storage.test/artifact?signature=secret",
        }
    )
    assert "test-private-key" not in json.dumps(data)
    assert "signature=secret" not in json.dumps(data)
    assert data["Authorization"] == "[redacted]"


def test_compute_disabled_never_contacts_remote(tmp_path):
    science, deps = make_tools(tmp_path, settings(tmp_path))
    from app.integration.scienceclaw.adapters.base import ToolUnavailable

    with pytest.raises(ToolUnavailable, match="compute is disabled"):
        asyncio.run(science.remote("A2", RemoteJob(tool="submit_alphafold3")))
    deps[-1].client.list_tools.assert_not_called()
    deps[-1].client.call.assert_not_called()


def test_nebius_discovery_preserves_server_schema(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager

    from app.nebius.client import NebiusClient

    config = settings(tmp_path)
    schema = {"type": "object", "required": ["protein"]}
    session = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=SimpleNamespace(
                tools=[SimpleNamespace(name="model", description=" Model ", input_schema=schema)]
            )
        )
    )

    @asynccontextmanager
    async def open_session():
        yield session

    client = NebiusClient(config)
    monkeypatch.setattr(client, "_session", open_session)
    tools = asyncio.run(client.list_tools())
    assert tools[0].input_schema == schema
    assert tools[0].description == "Model"


@pytest.mark.parametrize("pending", [True, False])
def test_mcp_error_envelope_preserves_pending_only_when_opted_in(tmp_path, monkeypatch, pending):
    from contextlib import asynccontextmanager

    from app.nebius.client import NebiusClient

    config = settings(tmp_path)
    payload = {"error": {"code": "OPERATION_PENDING", "operation_id": "op-test"}}
    result = SimpleNamespace(is_error=True, structured_content=payload, content=[])
    session = SimpleNamespace(call_tool=AsyncMock(return_value=result))

    @asynccontextmanager
    async def open_session():
        yield session

    client = NebiusClient(config)
    monkeypatch.setattr(client, "_session", open_session)
    if pending:
        assert asyncio.run(client.call("model", {}, allow_pending=True)) == payload
    else:
        with pytest.raises(NebiusError):
            asyncio.run(client.call("model", {}))


@pytest.mark.parametrize(
    ("agent", "tool", "code"),
    [
        ("A3", "infer_admet_ai_native", "MOLECULE_GENERATION_REQUIRED"),
        ("A6", "run_mdprecheck", "MD_TRAJECTORY_REQUIRED"),
    ],
)
def test_prerequisite_model_does_not_complete_main_science(tmp_path, agent, tool, code):
    config = settings(tmp_path, agent_compute_enabled=True)
    science, deps = make_tools(tmp_path, config)
    deps[-1].client.list_tools.return_value = [RemoteTool(tool, "", {"type": "object"})]
    deps[-1].client.call.return_value = {"status": "SUCCEEDED", "result": {"passed": True}}
    data, _ = asyncio.run(science.remote(agent, RemoteJob(tool=tool)))
    assert data["_status"] == "BLOCKED"
    assert data["_error_code"] == code


def test_duplicate_worker_cannot_overwrite_evidence(tmp_path):
    science, _ = make_tools(tmp_path, settings(tmp_path))
    asyncio.run(science.execute("A1"))
    path = tmp_path / "A1_science.json"
    original = path.read_bytes()
    with pytest.raises(ContractViolation):
        asyncio.run(science.execute("A1"))
    assert path.read_bytes() == original
    assert len(science.ledger.events()) == 1


def test_nonfinite_remote_result_is_failed_and_recorded(tmp_path):
    config = settings(tmp_path, agent_compute_enabled=True)
    request = RunRequest(jobs={"A2": RemoteJob(tool="submit_alphafold3")})
    science, deps = make_tools(tmp_path, config, request)
    science.observations["A1"] = {"status": "SUCCEEDED"}
    deps[-1].client.list_tools.return_value = [
        RemoteTool("submit_alphafold3", "", {"type": "object"})
    ]
    deps[-1].client.call.return_value = {
        "status": "SUCCEEDED",
        "result": {"confidence": float("nan")},
    }
    result = asyncio.run(science.execute("A2"))
    assert result["status"] == "FAILED"
    assert result["metrics"] == []
    assert science.ledger.events()[0]["status"] == "FAILED"
    assert science.ledger.verify()[0]
