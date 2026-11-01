"""Adapters to Dockshift's services; this module contains no scientific engines."""

from __future__ import annotations

import json
from dataclasses import asdict

from app.literature.models import SearchRequest
from app.nebius.client import NebiusError, NebiusNotConfiguredError

from .privacy import Redactor
from .scienceclaw.adapters.base import ToolFailed, ToolUnavailable
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
        self.verified_outputs = {}
        self.progress = lambda *args: None
        self.candidate_workflow = None
        self.scientific_preparation = None
        self.collective_workflow = None

    def require_parents(self, agent):
        from .scienceclaw.runtime.engine import SPECS

        parents = next(s.parents for s in SPECS if s.agent_id == agent)
        if agent == "A7":
            return
        if self.request.workflow == "collective":
            # Branch-specific typed bindings are enforced by CollectiveWorkflow.
            parents = () if agent == "A1" else ("A1",)
        if self.request.workflow == "candidate" and agent == "A6" and self.request.md_review:
            parents = ("A5a",)
        if self.request.workflow == "preparation" and agent == "A6":
            parents = ("A5a",)
        if self.request.workflow == "candidate" and agent == "A3":
            parents = ("A1",)  # QSAR/ADMET do not require a protein structure.
        if self.request.workflow == "candidate" and agent == "A5a":
            parents = ("A1",)  # The candidate identity is checked from real screening output.
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
            if (
                agent == "A3"
                and status == "SUCCEEDED"
                and "qsar" in payload
                and self.request.workflow != "candidate"
            ):
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
        except ToolFailed as exc:
            status, code, payload = "FAILED", exc.error_code, {}
            detail = exc.detail
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
        typed = []
        if self.collective_workflow:
            typed = [
                a
                for key, a in self.collective_workflow.records.items()
                if (key == "target" and agent == "A1")
                or any(s.id == key and s.agent == agent for s in self.request.steps)
            ]
        event = AgentEvent(
            run_id=self.run_id,
            agent=agent,
            event_type="DOCKSHIFT_TOOL_RESULT",
            status=WorkerState(status),
            target_accession=self.request.target.accession,
            outputs=[artifact, *[ArtifactRef(**a) for a in typed]],
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
            "artifacts": [asdict(artifact), *typed],
            "metrics": [asdict(m) for m in metrics],
            "limitations": payload.get("limitations", []),
        }

    async def dispatch(self, agent):
        if self.request.workflow == "collective":
            from .collective import CollectiveWorkflow

            if self.collective_workflow is None:
                self.collective_workflow = CollectiveWorkflow(self)
            return await self.collective_workflow.dispatch(agent)
        if self.request.workflow == "preparation":
            from .scientific_preparation import ScientificPreparation

            if self.scientific_preparation is None:
                self.scientific_preparation = ScientificPreparation(self)
            return await self.scientific_preparation.dispatch(agent)
        if self.request.workflow == "candidate":
            from .candidate import CandidateWorkflow

            if self.candidate_workflow is None:
                self.candidate_workflow = CandidateWorkflow(self)
            return await self.candidate_workflow.dispatch(agent)
        return await self.dispatch_advanced(agent)

    async def dispatch_advanced(self, agent):
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
            intact = all(
                ArtifactRef(**a).verify()
                for e in self.ledger.events()
                for a in e.get("outputs", [])
            )
            if not intact:
                raise ValueError("Scientific artifact integrity failed during independent audit")
            self.verified_outputs["review"] = {
                "ledger_verified": True,
                "artifact_hashes_verified": intact,
                "incomplete_agents": blocked,
                "redesign": "ABSTAINED",
                "method": "Deterministic integrity and completeness audit; LLM review is separate",
                "findings": [
                    "QSAR and ADMET predictions are distinct from measured target inhibition.",
                    "No docking or MD evidence can be inferred from ADMET endpoints.",
                ],
            }
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
        if agent == "A6" and job.tool.startswith("submit_"):
            from .md_execution import execute_md

            return await execute_md(self, job)
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
        if job.tool in ("run_mdprecheck", "infer_admet_ai_native"):
            return {
                "_status": "BLOCKED",
                "_error_code": (
                    "MD_TRAJECTORY_REQUIRED"
                    if job.tool == "run_mdprecheck"
                    else "MOLECULE_GENERATION_REQUIRED"
                ),
            }, "Prerequisite tools cannot complete the scientific role; use a reviewed workflow."
        from .artifact_io import expand_archives
        from .remote import RemoteRunner
        from .scientific_outputs import validate_output

        result = await RemoteRunner(
            self.settings, self.nebius.client, self.out, self.run_id
        ).execute(agent, job.tool, job.arguments, job.operation_id)
        self.verified_outputs[agent + "_operation"] = result
        if result["status"] == "PENDING":
            return {
                **result,
                "_status": "BLOCKED",
                "_error_code": "REMOTE_OPERATION_PENDING",
            }, "Scientific operation pending; resume only polls the same operation."
        expand_archives(result, self.out, self.settings.agent_max_artifact_bytes, self.redact)
        if job.tool in ("run_mdprecheck", "infer_admet_ai_native", "infer_diffdock_native"):
            raise ToolUnavailable(
                "SPECIALIZED_WORKFLOW_REQUIRED",
                "Use the managed candidate or collective workflow for identity-bound validation.",
            )
        validated = validate_output(job.tool, result, job.acceptance, self.out)
        self.verified_outputs[agent + "_validated"] = validated
        return {
            "native": result,
            "validated": validated,
        }, "Model-specific output checks passed; scientific review remains required."
