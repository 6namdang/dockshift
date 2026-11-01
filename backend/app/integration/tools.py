"""Adapters to Dockshift's services; this module contains no scientific engines."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from jsonschema import Draft202012Validator

from app.literature.models import SearchRequest
from app.nebius.client import NebiusError, NebiusNotConfiguredError
from app.nebius.service import _unwrap

from .privacy import Redactor
from .scienceclaw.adapters.base import ToolUnavailable
from .scienceclaw.adapters.chemistry import RDKitAdapter
from .scienceclaw.contracts import (
    AgentEvent,
    ArtifactRef,
    Channel,
    EvidenceState,
    Metric,
    WorkerState,
)
from .scienceclaw.ledger import AppendOnlyLedger
from .scienceclaw.validation import TargetIdentity

# Only known scientific tools are callable; lifecycle tools are used internally.
ROLE_TOOLS = {
    "A1": (),
    "A2": (
        "submit_alphafold3",
        "infer_openfold2_native",
        "infer_openfold3_native",
        "submit_esmfold2",
    ),
    "A3": ("genmol_generate", "molmim_run_native", "infer_admet_ai_native"),
    "A4": (
        "infer_proteinmpnn_native",
        "submit_rfdiffusion",
        "submit_proteina_complexa",
        "submit_rfd4_proteina",
        "submit_boltzgen",
    ),
    "A5a": ("infer_diffdock_native",),
    "A5b": (
        "boltz2_predict_native",
        "submit_protenix_v2",
        "submit_alphafold3",
        "infer_openfold3_native",
    ),
    "A6": (
        "submit_gromacs_workflow",
        "submit_amber_workflow",
        "submit_openmm_workflow",
        "run_mdprecheck",
    ),
    "A7": (),
}


def role_tools(settings):
    roles = dict(ROLE_TOOLS)
    if settings.agent_nebius_binder_tool:
        roles["A4"] = (*roles["A4"], settings.agent_nebius_binder_tool)
    return roles


def remote_state(payload: dict) -> tuple[str, str | None]:
    """Accepted, pending, error and empty payloads are never completed science."""
    operation = payload.get("operation") or {}
    if not isinstance(operation, dict):
        operation = {}
    error = payload.get("error")
    envelope = error if isinstance(error, dict) else {}
    operation_id = (
        operation.get("id")
        or operation.get("operation_id")
        or payload.get("operation_id")
        or envelope.get("operation_id")
    )
    state = str(operation.get("status") or payload.get("status") or "").upper()
    if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
        return "FAILED", operation_id
    if state in {"PENDING", "QUEUED", "RUNNING", "ACCEPTED", "SUBMITTED"}:
        return "BLOCKED", operation_id
    if error:
        return ("BLOCKED" if operation_id or "ADMISSION" in str(error) else "FAILED"), operation_id
    # Require an explicit success and actual scientific output, not just a job id.
    output = any(
        payload.get(k)
        for k in (
            "result",
            "artifact",
            "artifacts",
            "poses",
            "molecules",
            "sequences",
            "predictions",
        )
    )
    if state in {"SUCCEEDED", "SUCCESS", "COMPLETED", "COMPLETE"} and output:
        return "SUCCEEDED", operation_id
    return "BLOCKED", operation_id


class DockshiftTools:
    def __init__(self, settings, request, out, run_id, literature, qsar, structural, nebius):
        self.settings, self.request, self.out, self.run_id = settings, request, out, run_id
        self.redact = Redactor(settings)
        self.literature, self.qsar = literature, qsar
        self.structural, self.nebius = structural, nebius
        self.ledger = AppendOnlyLedger(out / "scientific_ledger.jsonl")
        self.observations = {}
        self.redesign = None
        self.cycle = 0

    def require_parents(self, agent):
        from .scienceclaw.runtime.engine import SPECS

        parents = next(s.parents for s in SPECS if s.agent_id == agent)
        if agent == "A7":
            return
        missing = [p for p in parents if self.observations.get(p, {}).get("status") != "SUCCEEDED"]
        if missing:
            raise ToolUnavailable(
                "UPSTREAM_REQUIRED", "Incomplete upstream science: " + ", ".join(missing)
            )

    async def execute(self, agent):
        self.ledger.claim(agent, None)
        metrics, channel = [], None
        try:
            self.require_parents(agent)
            payload, detail = await self.dispatch(agent)
            json.dumps(payload, allow_nan=False)
            status = payload.pop("_status", "SUCCEEDED")
            code = payload.pop("_error_code", None)
            # Extract only explicitly typed local predictions; remote numbers remain in
            # their original result artifact until a model-specific validator exists.
            if agent == "A3" and status == "SUCCEEDED" and "qsar" in payload:
                channel = Channel.QSAR_PREDICTION
                for row in payload["qsar"]["predictions"]:
                    if row.get("predicted_pic50") is not None and not row.get("error"):
                        metrics.append(
                            Metric.computed(
                                "predicted_pic50:" + row["smiles"],
                                row["predicted_pic50"],
                                "pIC50",
                                "Dockshift published hTERT XGBoost QSAR; prediction, not assay",
                            )
                        )
        except (ToolUnavailable, NebiusNotConfiguredError) as exc:
            status, code = "BLOCKED", getattr(exc, "error_code", "NEBIUS_NOT_CONFIGURED")
            payload, detail = {}, str(exc)
        except NebiusError:
            status, code, payload = "FAILED", "NEBIUS_CALL_FAILED", {}
            detail = "Nebius MCP call failed; no scientific result was accepted."
        except Exception as exc:
            status, code, payload = "FAILED", type(exc).__name__, {}
            detail = "Scientific tool execution or validation failed."
        if status != "SUCCEEDED":
            metrics = []
        payload, detail = self.redact(payload), self.redact(detail)
        # Persist one immutable receipt even for a failure. No exception payload can
        # echo a credential into an API response or evidence artifact.
        path = self.out / f"{agent}_science.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(
                {"status": status, "detail": detail, "payload": payload},
                handle,
                indent=2,
                allow_nan=False,
            )
        artifact = ArtifactRef.of(
            path, "scientific_result" if status == "SUCCEEDED" else "tool_receipt"
        )
        event = AgentEvent(
            run_id=self.run_id,
            agent=agent,
            event_type="DOCKSHIFT_TOOL_RESULT",
            status=WorkerState(status),
            target_accession=self.request.target.accession,
            outputs=[artifact],
            metrics=metrics,
            evidence_state=EvidenceState.EXPERIMENT_REQUIRED,
            channel=channel,
            error_code=code if status != "SUCCEEDED" else None,
            note=detail,
            input_artifact_hashes=[
                a["sha256"] for p in self.observations.values() for a in p.get("artifacts", [])
            ],
        )
        self.ledger.append(event)
        return {
            "status": status,
            "detail": detail,
            "error_code": code,
            "artifacts": [asdict(artifact)],
            "metrics": [asdict(m) for m in metrics],
            "limitations": payload.get("limitations", []),
        }

    async def dispatch(self, agent):
        if agent == "A1":
            issues = TargetIdentity(**self.request.target.model_dump()).check()
            if (
                self.request.target.species != "Homo sapiens"
                or self.request.target.label.lower() != "htert"
            ):
                issues.append("This integration currently supports human hTERT only.")
            if issues:
                raise ToolUnavailable("TARGET_IDENTITY_REQUIRED", "; ".join(issues))
            data = {
                "target": self.request.target.model_dump(),
                "verification": (
                    "Caller-attested identity; no live primary-source verification claimed."
                ),
            }
            if self.request.literature_query:
                response = await self.literature.search(
                    SearchRequest(
                        query=self.request.literature_query,
                        max_results_per_source=5,
                        full_text="never",
                    )
                )
                data["literature"] = response.model_dump(mode="json")
                if response.errors:
                    data.update(_status="BLOCKED", _error_code="LITERATURE_INCOMPLETE")
            return data, "Identity assessment and requested literature retrieval; no assay claim."
        if agent == "A7":
            ok, error = self.ledger.verify()
            if not ok:
                raise ValueError(error)
            blocked = [a for a, r in self.observations.items() if r["status"] != "SUCCEEDED"]
            return {
                "upstream_incomplete": blocked,
                "ledger_verified": True,
                "redesign": "ABSTAINED",
                "limitations": [
                    "Scores from different models are never pooled.",
                    "Remote outputs require scientist review.",
                    "No experimental efficacy or binding claim.",
                ],
            }, "Deterministic evidence audit; an LLM review is recorded separately when enabled."
        if agent == "A2" and self.request.alignment:
            if not self.settings.agent_compute_enabled:
                raise ToolUnavailable(
                    "COMPUTE_APPROVAL_REQUIRED", "Agent scientific compute is disabled."
                )
            result = await self.structural.tmalign(self.request.alignment)
            data = result.model_dump(mode="json")
            if data["status"] != "success":
                data.update(_status="FAILED", _error_code="ALIGNMENT_FAILED")
            return (
                data,
                "Dockshift TM-align; alignment alone does not establish pocket equivalence.",
            )
        if agent == "A3" and self.request.compounds and agent not in self.request.jobs:
            audits = RDKitAdapter().deduplicate(
                [RDKitAdapter().audit(s) for s in self.request.compounds]
            )
            valid = [a.canonical_smiles for a in audits if a.valid]
            if not valid:
                raise ToolUnavailable(
                    "NO_VALID_COMPOUNDS", "No supplied compound passed chemical validation."
                )
            prediction = await self.qsar.predict_activity(valid)
            profile = await self.qsar.profile(valid)
            data = {
                "audits": [asdict(a) for a in audits],
                "qsar": prediction.model_dump(mode="json"),
                "profiles": profile.model_dump(mode="json"),
                "limitations": ["Supplied-candidate screening, not de novo generation."],
            }
            if any(p.error or p.predicted_pic50 is None for p in prediction.predictions):
                data.update(_status="FAILED", _error_code="QSAR_INCOMPLETE")
            return data, "Existing Dockshift QSAR and profiles with source-system Vchem validation."
        job = self.request.jobs.get(agent)
        if not job:
            raise ToolUnavailable(
                "SCIENTIFIC_INPUT_REQUIRED", f"{agent} requires reviewed tool inputs."
            )
        return await self.remote(agent, job)

    async def remote(self, agent, job):
        allowed = role_tools(self.settings).get(agent, ())
        if job.tool not in allowed:
            raise ToolUnavailable(
                "ROLE_TOOL_UNAVAILABLE", "No reviewed model binding for this role/tool."
            )
        if not self.settings.agent_compute_enabled and not job.operation_id:
            raise ToolUnavailable(
                "COMPUTE_APPROVAL_REQUIRED", "Agent scientific compute is disabled."
            )
        tools = {t.name: t for t in await self.nebius.client.list_tools()}
        if job.tool not in tools:
            raise ToolUnavailable(
                "NEBIUS_TOOL_UNAVAILABLE", "Selected model is absent from Nebius discovery."
            )
        if job.operation_id:
            payload = _unwrap(await self.nebius.operation(job.operation_id))
            state, _ = remote_state(payload)
            operation = payload.get("operation") or {}
            if str(operation.get("status") or payload.get("status")).upper() in {
                "SUCCEEDED",
                "SUCCESS",
                "COMPLETED",
            }:
                payload = _unwrap(await self.nebius.operation_result(job.operation_id))
        else:
            arguments = dict(job.arguments)
            schema = tools[job.tool].input_schema
            if not schema:
                raise ToolUnavailable(
                    "NEBIUS_SCHEMA_REQUIRED", "Server did not advertise an input schema."
                )
            # Durable job key is independent of LLM output and reused by the remote service.
            if "idempotency_key" in schema.get("properties", {}):
                arguments["idempotency_key"] = f"{self.run_id}-{agent}"
            Draft202012Validator(schema).validate(arguments)
            (self.out / f"{agent}_nebius_submission.json").write_text(
                json.dumps(
                    self.redact({"tool": job.tool, "schema": schema, "arguments": arguments}),
                    indent=2,
                    allow_nan=False,
                )
            )
            payload = _unwrap(
                await self.nebius.client.call(job.tool, arguments, allow_pending=True)
            )
        state, operation_id = remote_state(payload)
        operation_id = operation_id or job.operation_id
        code = "REMOTE_OPERATION_PENDING" if operation_id else "REMOTE_OUTPUT_UNVERIFIED"
        if state == "FAILED":
            code = "REMOTE_OPERATION_FAILED"
        data: dict[str, Any] = {
            "tool": job.tool,
            "operation_id": operation_id,
            "remote": payload,
            "_status": state,
            "limitations": [
                "Raw model outputs retain native names and units.",
                "Computational output requires scientific review.",
            ],
        }
        if state != "SUCCEEDED":
            data["_error_code"] = code
        # GenMol outputs must pass chemical validation before downstream docking.
        if state == "SUCCEEDED" and agent == "A3" and job.tool != "infer_admet_ai_native":
            molecules = payload.get("molecules") or (payload.get("result") or {}).get("molecules")
            if not isinstance(molecules, list) or not molecules:
                data.update(_status="BLOCKED", _error_code="GENERATED_CHEMISTRY_REVIEW_REQUIRED")
            else:
                audits = [
                    RDKitAdapter().audit(m if isinstance(m, str) else m.get("smiles", ""))
                    for m in molecules
                ]
                data["chemical_audits"] = [asdict(a) for a in audits]
                if not all(a.valid for a in audits):
                    data.update(_status="FAILED", _error_code="INVALID_GENERATED_CHEMISTRY")
        if job.tool == "infer_admet_ai_native" and state == "SUCCEEDED":
            data.update(_status="BLOCKED", _error_code="MOLECULE_GENERATION_REQUIRED")
        # MD preparation is a prerequisite, never an executed trajectory.
        if job.tool == "run_mdprecheck" and state == "SUCCEEDED":
            data.update(_status="BLOCKED", _error_code="MD_TRAJECTORY_REQUIRED")
        return data, "Nebius scientific tool receipt; pending jobs are polled, never resubmitted."
