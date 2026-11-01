"""Verified continuation of an incomplete demo under its ORIGINAL shared budget."""

import copy
import json
from decimal import Decimal

from .scienceclaw.contracts import (
    AgentEvent,
    ArtifactRef,
    Channel,
    EvidenceState,
    Metric,
    MetricStatus,
    WorkerState,
)
from .scienceclaw.ledger import AppendOnlyLedger


def restore_demo(runtime):
    from .service import IntegrationService

    science = runtime.science
    source_id = science.request.source_run
    source = IntegrationService(
        science.settings, science.literature, science.qsar, science.structural, science.nebius
    )
    prior = source.report(source_id)
    if prior.get("workflow") != "demonstration" or prior.get("candidate_name") != "BIBR1532":
        raise ValueError("Continuation requires the same verified hTERT/BIBR1532 demo")
    ledger = AppendOnlyLedger(source.directory(source_id) / "scientific_ledger.jsonl")
    if not ledger.verify()[0]:
        raise ValueError("Source ledger integrity failed")
    usage = prior["reasoning_usage"]
    provider = runtime.provider
    provider.calls = usage["attempted_requests"]
    provider.reserved_usd = Decimal(usage["reserved_cost_usd"])
    provider.agent_calls = copy.deepcopy(usage["per_agent_requests"])
    provider.usage = copy.deepcopy(usage["usage"])
    if provider.calls >= 24 or provider.reserved_usd >= Decimal(".10"):
        raise ValueError("Original demonstration budget is exhausted")
    completed = [r for r in prior["agents"] if r["llm_decision_completed"]]
    completed_ids = {r["agent"] for r in completed}
    if not completed_ids:
        raise ValueError("No completed source workers to reuse")
    for row in completed:
        row = copy.deepcopy(row)
        for ref in row["artifacts"]:
            if not ArtifactRef(**ref).verify():
                raise ValueError("Source worker artifact changed")
        row["reused_from"] = source_id
        runtime.results.append(row)
        runtime.latest[row["agent"]] = row
        runtime.register(row["artifacts"])
        science.observations[row["agent"]] = {**row, "status": row["scientific_status"]}
        science.progress(
            row["agent"], row["scientific_status"], "Verified prior reasoning/tool evidence reused."
        )
    # Re-chain verified source evidence; no source event or file is overwritten.
    for event in ledger.events():
        if event["agent"].split(".")[0] not in completed_ids:
            continue
        refs = [ArtifactRef(**a) for a in event.get("outputs", [])]
        if not all(a.verify() for a in refs):
            raise ValueError("Source scientific artifact changed")
        science.ledger.append(
            AgentEvent(
                run_id=science.run_id,
                agent=event["agent"],
                event_type="VERIFIED_DEMO_SOURCE_EVENT_REUSED",
                status=WorkerState(event["status"]),
                outputs=refs,
                target_accession=event.get("target_accession"),
                candidate_id=event.get("candidate_id"),
                protocol_id=event.get("protocol_id"),
                metrics=[
                    Metric(**{**m, "status": MetricStatus(m["status"])})
                    for m in event.get("metrics", [])
                ],
                channel=Channel(event["channel"]) if event.get("channel") else None,
                evidence_state=EvidenceState(event["evidence_state"])
                if event.get("evidence_state")
                else None,
                error_code=event.get("error_code"),
                tool_versions=event.get("tool_versions", {}),
                input_artifact_hashes=event.get("input_artifact_hashes", []),
                note=f"Reused {source_id}:{event['event_id']}. " + (event.get("note") or ""),
            )
        )
    runtime.handoffs = [copy.deepcopy(h) for h in prior["handoffs"] if h["to"] in completed_ids]
    science.verified_outputs = copy.deepcopy(prior["outputs"])
    science.verified_outputs["demonstration_continuation"] = {
        "source_run": source_id,
        "original_attempted_requests": provider.calls,
        "original_reserved_cost_usd": str(provider.reserved_usd),
        "reused_workers": sorted(completed_ids),
        "original_request_limit": 24,
        "original_cost_limit_usd": ".10",
        "prior_usage_records_missing": provider.calls - len(provider.usage),
        "note": (
            "Prior invalid tool response consumed one real inference; "
            "its full native usage was not retained by the previous validator."
        ),
    }
    from .demonstration import DemonstrationWorkflow

    science.demonstration_workflow = DemonstrationWorkflow(science)
    # MD drafting needs these exact previously discovered input schemas.
    for tool in (
        "infer_diffdock_native",
        "submit_gromacs_workflow",
        "submit_amber_workflow",
        "submit_openmm_workflow",
    ):
        path = source.artifact(source_id, "schema_" + tool + ".json")
        science.demonstration_workflow.preparation.state.setdefault("schemas", {})[tool] = (
            json.loads(path.read_text())
        )
    runtime.trace.emit(
        "demo_source_restored",
        source_run=source_id,
        reused_workers=sorted(completed_ids),
        attempted_requests=provider.calls,
        reserved_cost_usd=str(provider.reserved_usd),
    )
    return prior, completed_ids
