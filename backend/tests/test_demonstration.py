"""Offline limits and one-shot admission; no paid inference or scientific jobs."""

import pytest

from app.config import Settings
from app.integration.demonstration import demo_request
from app.integration.service import IntegrationService


def settings(tmp_path, **kw):
    return Settings(
        _env_file=None,
        agent_artifact_root=tmp_path,
        agent_demo_enabled=True,
        anthropic_max_calls=24,
        anthropic_max_cost_usd=0.10,
        **kw,
    )


def test_demo_admits_only_once_and_preserves_limits(tmp_path):
    service = IntegrationService(settings(tmp_path), None, None, None, None)
    request = demo_request()
    assert request.compounds == ["BIBR1532"] and request.target.accession == "O14746"
    assert request.budget.max_submissions == 0
    assert request.budget.max_llm_calls == 24 and request.budget.max_llm_cost_usd == 0.10
    service._prepare(request)
    with pytest.raises(ValueError, match="already admitted"):
        service._prepare(request)


@pytest.mark.parametrize("gate", ["agent_compute_enabled", "agent_admet_enabled"])
def test_demo_rejects_enabled_science(tmp_path, gate):
    service = IntegrationService(settings(tmp_path, **{gate: True}), None, None, None, None)
    with pytest.raises(ValueError, match="disabled"):
        service._prepare(demo_request())
    assert not list(tmp_path.iterdir())


def test_demo_rejects_request_budget_increase(tmp_path):
    service = IntegrationService(settings(tmp_path), None, None, None, None)
    request = demo_request()
    request.budget.max_llm_calls = 25
    with pytest.raises(ValueError, match="ceiling"):
        service._prepare(request)


def test_demo_cannot_start_on_ordinary_server(tmp_path):
    config = Settings(_env_file=None, agent_artifact_root=tmp_path)
    service = IntegrationService(config, None, None, None, None)
    with pytest.raises(ValueError, match="not enabled"):
        service._prepare(demo_request())


def test_continuation_carries_original_spend_and_verified_evidence(tmp_path):
    """Synthetic checkpoint fixture; no real API/model execution."""
    import hashlib
    import json
    from dataclasses import asdict
    from decimal import Decimal
    from pathlib import Path
    from types import SimpleNamespace

    from app.integration.demo_checkpoint import restore_demo
    from app.integration.scienceclaw.contracts import AgentEvent, ArtifactRef, Metric, WorkerState
    from app.integration.scienceclaw.ledger import AppendOnlyLedger
    from app.integration.tools import DockshiftTools

    config = settings(tmp_path)
    source_id = "agents-" + "a" * 32
    source = tmp_path / source_id
    source.mkdir()
    receipt = source / "A1_science.json"
    receipt.write_text('{"fixture":"SYNTHETIC - not scientific evidence"}')
    ref = ArtifactRef.of(receipt, "tool_receipt")
    ledger = AppendOnlyLedger(source / "scientific_ledger.jsonl")
    ledger.append(
        AgentEvent(
            run_id=source_id,
            agent="A1",
            event_type="SYNTHETIC",
            status=WorkerState.SUCCEEDED,
            outputs=[ref],
            metrics=[Metric.computed("synthetic_fixture_value", 1, "test-unit", "TEST ONLY")],
        )
    )
    fixture_root = Path(__file__).parent / "fixtures" / "nebius"
    for tool in (
        "infer_diffdock_native",
        "submit_gromacs_workflow",
        "submit_amber_workflow",
        "submit_openmm_workflow",
    ):
        (source / ("schema_" + tool + ".json")).write_bytes(
            (fixture_root / (tool + ".json")).read_bytes()
        )
    report = {
        "workflow": "demonstration",
        "candidate_name": "BIBR1532",
        "outputs": {},
        "handoffs": [],
        "reasoning_usage": {
            "attempted_requests": 3,
            "reserved_cost_usd": ".001",
            "per_agent_requests": {"A1": 2, "A6": 1},
            "usage": [{}, {}],
        },
        "agents": [
            {
                "agent": "A1",
                "scientific_status": "SUCCEEDED",
                "llm_decision_completed": True,
                "artifacts": [asdict(ref)],
            }
        ],
    }
    (source / "report.json").write_text(json.dumps(report))
    (source / "manifest.json").write_text(
        json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()})
    )
    out = tmp_path / ("agents-" + "b" * 32)
    out.mkdir()
    science = DockshiftTools(
        config,
        demo_request().model_copy(update={"source_run": source_id}),
        out,
        out.name,
        None,
        None,
        None,
        SimpleNamespace(client=SimpleNamespace()),
    )
    runtime = SimpleNamespace(
        science=science,
        provider=SimpleNamespace(),
        results=[],
        latest={},
        handoffs=[],
        register=lambda refs: None,
        trace=SimpleNamespace(emit=lambda *args, **kwargs: None),
    )
    prior, complete = restore_demo(runtime)
    assert complete == {"A1"}
    assert runtime.provider.calls == 3
    assert runtime.provider.reserved_usd == Decimal(".001")
    assert runtime.provider.agent_calls == {"A1": 2, "A6": 1}
    assert science.ledger.verify()[0]
    assert science.ledger.events()[0]["metrics"][0]["value"] == 1
    assert ref.verify()
    assert (
        science.verified_outputs["demonstration_continuation"]["prior_usage_records_missing"] == 1
    )
