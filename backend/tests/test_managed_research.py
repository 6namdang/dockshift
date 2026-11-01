"""Offline native-schema, execution and original API regression tests.

Network responses here are explicit test doubles. Live verification is recorded
separately; these tests never submit paid or scientific inference.
"""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.integration.candidate import CandidateWorkflow
from app.integration.models import RunRequest
from app.integration.nebius_llm import NebiusLLMProvider
from app.integration.remote import RemoteRunner
from app.integration.scienceclaw.adapters.base import ToolFailed, ToolUnavailable
from app.integration.service import IntegrationService
from app.literature.models import SearchResponse
from app.nebius.client import RemoteTool
from app.qsar import QsarService


def native_admet(smiles="CCO"):
    return {
        "model_id": "admet-ai",
        "model_version": "test-version",
        "status": "succeeded",
        "molecule_count": 1,
        "succeeded": 1,
        "failed": 0,
        "results": [
            {
                "id": "candidate-1",
                "status": "succeeded",
                "input_smiles": smiles,
                "canonical_smiles": smiles,
                "predictions": {"hERG": 0.2, "AMES": 0.3, "Solubility_AqSolDB": -1.2},
            }
        ],
        "endpoint_metadata": {
            "hERG": {"units": "-", "species": "human", "task_type": "classification"},
            "AMES": {"units": "-", "species": "salmonella", "task_type": "classification"},
            "Solubility_AqSolDB": {
                "units": "log(mol/L)",
                "species": "-",
                "task_type": "regression",
            },
        },
        "limitations": ["Test fixture"],
    }


def result_for(document):
    return {
        "tool": "infer_admet_ai_native",
        "operation_id": "op-test",
        "artifacts": [
            {"data": document, "hash_verified": True, "filename": "A3_admet_artifact_0.json"}
        ],
    }


@pytest.mark.parametrize("mutation", ["identity", "units", "nan", "range", "status", "version"])
def test_native_admet_rejects_invalid_scientific_output(mutation):
    document = native_admet()
    if mutation == "identity":
        document["results"][0]["input_smiles"] = "CC"
    elif mutation == "units":
        del document["endpoint_metadata"]["AMES"]["units"]
    elif mutation == "nan":
        document["results"][0]["predictions"]["AMES"] = float("nan")
    elif mutation == "range":
        document["results"][0]["predictions"]["AMES"] = 2
    elif mutation == "status":
        document["results"][0]["status"] = "failed"
    else:
        del document["model_version"]
    with pytest.raises((ToolUnavailable, ValueError)):
        CandidateWorkflow.validate_admet(result_for(document), "CCO")


def test_native_admet_preserves_units_and_species():
    validated = CandidateWorkflow.validate_admet(result_for(native_admet()), "CCO")
    assert validated["model_version"] == "test-version"
    assert validated["endpoints"][1]["species"] == "salmonella"
    assert validated["endpoints"][2]["units"] == "log(mol/L)"


def configure(tmp_path, **kwargs):
    return Settings(
        _env_file=None, agent_artifact_root=tmp_path, scientific_models_api_key=None, **kwargs
    )


def transport_patch(monkeypatch, data, *, wrong_hash=False, private=False):
    import app.integration.remote as remote

    original_client = httpx.AsyncClient
    requests = []

    def download(request):
        requests.append(request)
        return httpx.Response(200, content=data)

    monkeypatch.setattr(
        remote.socket,
        "getaddrinfo",
        lambda *a: [(2, 1, 6, "", ("127.0.0.1" if private else "8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        remote.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(download), **kwargs),
    )
    pointer = {
        "artifact_id": "fixture-artifact",
        "size_bytes": len(data),
        "sha256": "0" * 64 if wrong_hash else hashlib.sha256(data).hexdigest(),
    }
    return pointer, requests


def fake_mcp(pointer):
    async def call(tool, args, **kwargs):
        if tool == "infer_admet_ai_native":
            return {"operation": {"id": "op-test", "status": "QUEUED"}}
        if tool == "get_operation":
            return {"operation": {"id": "op-test", "status": "SUCCEEDED"}}
        if tool == "get_operation_result":
            return {"result": {"artifact": pointer}}
        if tool == "get_scientific_artifact":
            return {"artifact": pointer}
        if tool == "download_scientific_artifact":
            return {"handle": {"url": "https://artifacts.example/result?signature=test"}}
        raise AssertionError("Unexpected tool " + tool)

    return SimpleNamespace(
        list_tools=AsyncMock(
            return_value=[
                RemoteTool(
                    "infer_admet_ai_native",
                    "",
                    {
                        "type": "object",
                        "properties": {
                            "idempotency_key": {"type": "string"},
                            "wait_seconds": {"type": "integer"},
                        },
                    },
                )
            ]
        ),
        call=AsyncMock(side_effect=call),
    )


@pytest.mark.parametrize("failure", ["hash", "private", "none"])
def test_artifact_download_checks_hash_and_does_not_forward_credentials(
    tmp_path, monkeypatch, failure
):
    data = json.dumps(native_admet()).encode()
    pointer, requests = transport_patch(
        monkeypatch, data, wrong_hash=failure == "hash", private=failure == "private"
    )
    runner = RemoteRunner(configure(tmp_path), fake_mcp(pointer), tmp_path, "agents-test")
    if failure != "none":
        with pytest.raises(ToolFailed):
            asyncio.run(runner.retrieve("A3", pointer, 0))
        assert not list(tmp_path.glob("*artifact*"))
    else:
        artifact = asyncio.run(runner.retrieve("A3", pointer, 0))
        assert artifact["hash_verified"]
        assert (tmp_path / artifact["filename"]).read_bytes() == data
        assert all("authorization" not in request.headers for request in requests)


def test_managed_candidate_progress_results_artifacts_and_resume(tmp_path, monkeypatch):
    async def exercise():
        config = configure(tmp_path, agent_admet_enabled=True, agent_poll_interval_seconds=0.1)

        def primary(request):
            assert str(request.url).endswith("/O14746.json")
            return httpx.Response(
                200,
                json={
                    "primaryAccession": "O14746",
                    "organism": {"taxonId": 9606},
                    "genes": [{"geneName": {"value": "TERT"}}],
                    "sequence": {"value": "TESTSEQUENCE"},
                },
            )

        # Create this client before installing the isolated artifact transport.
        http = httpx.AsyncClient(transport=httpx.MockTransport(primary))
        pointer, _ = transport_patch(monkeypatch, json.dumps(native_admet()).encode())
        mcp = fake_mcp(pointer)
        structural = SimpleNamespace(
            capabilities=AsyncMock(
                return_value=SimpleNamespace(
                    model_dump=lambda **kw: {"tools": [], "status": "partial"}
                )
            )
        )
        literature = SimpleNamespace(
            search=AsyncMock(
                return_value=SearchResponse(
                    query="test", results=[], total_hits={}, errors=[], full_text_threshold=0.75
                )
            )
        )
        svc = IntegrationService(
            config, literature, QsarService(http, config), structural, SimpleNamespace(client=mcp)
        )
        try:
            started = await svc.start(RunRequest(workflow="candidate", compounds=["CCO"]))
            assert started["status"] == "QUEUED"
            await svc.close()
            progress = svc.progress(started["run_id"])
            assert len(progress["agents"]) == 8
            report = svc.report(started["run_id"])
            assert report["status"] == "BLOCKED"  # No binder, MD or live LLM asserted.
            assert report["candidate_screening_status"] == "COMPLETED"
            assert report["ledger_integrity"]["verified"]
            assert report["outputs"]["review"]["artifact_hashes_verified"]
            assert report["llm_agents_invoked"] == 0
            assert len(report["computational_evidence"]) == 4
            artifact = report["outputs"]["admet"]["artifacts"][0]
            assert svc.artifact(started["run_id"], artifact["filename"]).is_file()
            with pytest.raises(FileNotFoundError):
                svc.artifact(started["run_id"], "../request.json")
            mcp.call.reset_mock()
            # Revoke execution permission: existing-operation resume is read-only.
            config.agent_admet_enabled = False
            resumed = await svc.resume(started["run_id"])
            await svc.close()
            assert svc.report(resumed["run_id"])["candidate_screening_status"] == "COMPLETED"
            assert all(call.args[0] != "infer_admet_ai_native" for call in mcp.call.call_args_list)
            path = svc.artifact(resumed["run_id"], artifact["filename"])
            path.write_text("tampered")
            with pytest.raises(ValueError, match="integrity"):
                svc.report(resumed["run_id"])
        finally:
            await http.aclose()

    asyncio.run(exercise())


def test_remote_pending_is_not_completed_and_keeps_operation_id(tmp_path):
    config = configure(tmp_path, agent_remote_wait_seconds=0)
    mcp = fake_mcp({})
    runner = RemoteRunner(config, mcp, tmp_path, "test-run")
    result = asyncio.run(runner.execute("A3", "infer_admet_ai_native", {}))
    assert result["status"] == "PENDING"
    assert result["operation_id"] == "op-test"
    assert json.loads((tmp_path / "A3_operation.json").read_text())["operation_id"] == "op-test"
    assert all(c.args[0] != "get_operation_result" for c in mcp.call.call_args_list)


def test_original_qsar_and_structural_api_regressions(tmp_path, monkeypatch):
    import app.main as main

    config = configure(tmp_path)
    monkeypatch.setattr(main, "get_settings", lambda: config)
    with TestClient(main.create_app()) as client:
        prediction = client.post("/api/v1/qsar/htert/predict", json=["CCO"])
        assert prediction.status_code == 200
        assert isinstance(prediction.json()["predictions"][0]["predicted_pic50"], float)
        profile = client.post("/api/v1/qsar/htert/profile", json=["CCO"])
        assert profile.status_code == 200
        assert profile.json()["profiles"][0]["molecular_weight"] == pytest.approx(46.069, abs=0.01)
        assert client.post("/api/v1/qsar/htert/predict", json=[]).status_code == 422
        assert (
            client.get("/api/v1/qsar/htert/dataset", params={"compound": "CCO"}).status_code == 200
        )
        svg = client.get("/api/v1/qsar/htert/structure", params={"smiles": "CCO"})
        assert svg.status_code == 200 and "<svg" in svg.text
        assert client.get("/api/v1/structural/capabilities").status_code == 503
        assert client.post("/api/v1/literature/search", json={"query": ""}).status_code == 422
        assert client.get("/api/v1/pipeline/targets").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.post("/api/v1/agents/research", json={}).status_code == 503


def test_nebius_llm_does_not_fall_back_to_other_providers(tmp_path):
    config = configure(tmp_path, openai_api_key="test-only-unrelated-key")
    assert not NebiusLLMProvider(config).probe()["available"]
    with pytest.raises(ToolUnavailable, match="NEBIUS_LLM_REQUIRED"):
        NebiusLLMProvider(config).chat([], [])
    config.nebius_llm_api_key = SecretStr("test-nebius-key")
    config.agent_llm_enabled = True
    config.nebius_llm_model = "fixture-model"
    config.nebius_llm_base_url = "https://unrelated.example/v1"
    assert not NebiusLLMProvider(config).probe()["available"]


def test_managed_api_auth_progress_and_original_literature_structural_contracts(
    tmp_path, monkeypatch
):
    import time

    import app.main as main
    from app.structural.errors import PrerequisiteError

    config = configure(
        tmp_path,
        structural_rest_enabled=True,
        structural_api_token=SecretStr("test-execution-token"),
    )
    monkeypatch.setattr(main, "get_settings", lambda: config)
    app = main.create_app()
    auth = {"Authorization": "Bearer test-execution-token"}
    with TestClient(app) as client:
        assert client.post("/api/v1/agents/research", json={}).status_code == 401
        created = client.post("/api/v1/agents/research", headers=auth, json={})
        assert created.status_code == 202
        run_id = created.json()["run_id"]
        for _ in range(100):
            progress = client.get(f"/api/v1/agents/runs/{run_id}/progress", headers=auth)
            assert progress.status_code == 200
            if progress.json()["status"] not in {"RUNNING", "QUEUED"}:
                break
            time.sleep(0.02)
        assert progress.json()["status"] == "BLOCKED"
        assert len(progress.json()["agents"]) == 8
        artifact = f"/api/v1/agents/runs/{run_id}/artifacts/A1_science.json"
        assert client.get(artifact).status_code == 401
        assert client.get(artifact, headers=auth).json()["status"] == "BLOCKED"
        assert client.get(f"/api/v1/agents/runs/{run_id}/progress").status_code == 401
        assert client.post(f"/api/v1/agents/runs/{run_id}/resume", headers=auth).status_code == 409
        expected = SearchResponse(
            query="test", results=[], total_hits={}, errors=[], full_text_threshold=0.75
        )
        app.state.literature_service.search = AsyncMock(return_value=expected)
        literature = client.post("/api/v1/literature/search", json={"query": "test"})
        assert literature.status_code == 200
        assert literature.json() == expected.model_dump(mode="json")
        app.state.structural_service.tmalign = AsyncMock(
            side_effect=PrerequisiteError("Not installed")
        )
        structural = client.post(
            "/api/v1/structural/tmalign",
            headers=auth,
            json={"structure_a": {"path": "a.pdb"}, "structure_b": {"path": "b.pdb"}},
        )
        assert structural.status_code == 424
        assert structural.json()["detail"]["code"] == "prerequisite_unavailable"


def test_interrupted_run_is_blocked_without_automatic_replay(tmp_path):
    config = configure(tmp_path)
    svc = IntegrationService(config, None, None, None, None)
    run_id = svc._prepare(RunRequest())
    progress = svc.progress(run_id)
    assert progress["status"] == "BLOCKED"
    assert "restarted" in progress["detail"]
    assert not svc._tasks


def test_nebius_provider_preserves_native_tool_call_ids(tmp_path, monkeypatch):
    import app.integration.nebius_llm as module

    real_client = httpx.Client
    received = []

    def answer(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "fixture-model"}]})
        received.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "fixture-model",
                "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": []}}],
                "usage": {"total_tokens": 1},
            },
        )

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(answer), **kw),
    )
    config = configure(
        tmp_path,
        agent_llm_enabled=True,
        nebius_llm_model="fixture-model",
        nebius_llm_api_key=SecretStr("test-nebius-key"),
    )
    provider = NebiusLLMProvider(config)
    assert provider.probe()["catalog_verified"]
    result = provider.chat(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "original-call-id",
                        "function": {"name": "read_evidence", "arguments": {}},
                    }
                ],
            },
            {"role": "tool", "tool_name": "read_evidence", "content": "{}"},
        ],
        [],
    )
    assert received[0]["messages"][1]["tool_call_id"] == "original-call-id"
    assert received[0]["messages"][0]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert result["provider"] == "nebius"
    assert "test-nebius-key" not in json.dumps(received)
