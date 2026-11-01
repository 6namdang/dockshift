"""Dockshift binding of the existing eight-worker tool-calling runtime."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import asdict, replace

from .nebius_llm import NebiusLLMProvider
from .privacy import Redactor
from .scienceclaw.contracts import ArtifactRef
from .scienceclaw.report.export import acceptance_report, build_bundle
from .scienceclaw.runtime.engine import SPECS, AgentRuntime, Trace

# Remove engine-specific claims from the source demo. Actual engines come from receipts.
SPECS = tuple(
    replace(
        s,
        instructions=(
            f"Perform the {s.role} task using the configured Dockshift adapter. "
            "Report the exact engine, scope, native outputs and limitations in its receipt. "
            "An accepted operation is pending until results exist. Never pool model scores or "
            "infer potency from docking confidence. Block on missing prerequisites. "
            "Only A7 may propose redesign; this integration records proposals for scientist review."
        ),
    )
    for s in SPECS
)


class DisabledProvider:
    def probe(self):
        return {
            "available": False,
            "model": None,
            "detail": "Local LLM disabled; deterministic tool execution is not LLM agency.",
        }


class DockshiftRuntime(AgentRuntime):
    def __init__(self, root, science, loop, provider=None):
        self.root, self.out, self.run_id = root, science.out, science.run_id
        self.science, self.loop = science, loop
        self.redact = Redactor(science.settings)
        self.trace = Trace(self.out / "agent_execution_trace.jsonl", self.run_id)
        self.provider = provider or (
            NebiusLLMProvider(
                science.settings,
                max_calls=(
                    (
                        science.request.budget.max_llm_calls
                        if science.request.budget.approved_by
                        else 0
                    )
                    if science.request.workflow == "collective"
                    else 64
                ),
            )
            if science.request.use_nebius_llm and science.request.workflow != "preparation"
            else DisabledProvider()
        )
        self.probe = self.provider.probe()
        self.registry, self.latest = {}, {}
        self.results, self.handoffs, self.redesigns = [], [], []
        self.max_cycles = 0
        self.methods = {s.agent_id: self.bind(s.agent_id) for s in SPECS}
        self.specs = SPECS
        if science.request.workflow == "collective":
            self.specs = tuple(
                replace(s, parents=("A1",)) if s.agent_id == "A6" else s for s in SPECS
            )
        if science.request.workflow == "candidate":
            self.specs = tuple(
                replace(s, parents=("A1",), tool="screen_candidate") if s.agent_id == "A3" else s
                for s in SPECS
            )
        if science.request.workflow == "candidate" and science.request.md_review:
            self.specs = tuple(
                replace(s, parents=("A5a",)) if s.agent_id == "A6" else s for s in self.specs
            )
        if science.request.workflow == "preparation":
            names = {
                "A1": "verify_structural_sources",
                "A2": "audit_structure_inputs",
                "A3": "verify_reference_ligand",
                "A5a": "prepare_diffdock_request",
                "A6": "audit_md_prerequisites",
            }
            self.specs = tuple(
                replace(
                    s,
                    tool=names.get(s.agent_id, s.tool),
                    parents=("A5a",) if s.agent_id == "A6" else s.parents,
                )
                for s in SPECS
            )
        for spec in self.specs:
            self.trace.emit("agent_initialized", spec.agent_id, specification=asdict(spec))

    def write(self, name, data):
        return super().write(name, self.redact(data))

    def bind(self, agent):
        def execute():
            return asyncio.run_coroutine_threadsafe(self.science.execute(agent), self.loop).result()

        return execute

    def run(self):
        for spec in self.specs:
            self.science.progress(spec.agent_id, "RUNNING")
            result = self.invoke(spec, 0)
            self.science.progress(spec.agent_id, result["scientific_status"], result["detail"])
        # Preserve A7's structured feedback without automatically starting more compute.
        decision = self.latest["A7"]["decision"]
        self.redesigns.append(
            {
                "request": decision,
                "status": "REVIEW_REQUIRED"
                if decision and decision["redesign_target"] != "none"
                else "ABSTAINED",
                "additional_scientific_calculation": False,
            }
        )
        return self.export()

    def export(self):
        integrity = all(ArtifactRef(**a).verify() for a in self.registry.values())
        bundle = build_bundle(self.science.ledger, self.run_id)
        agent_statuses = [r["agent_status"] for r in self.results]
        science_statuses = [r["scientific_status"] for r in self.results]
        status = (
            "FAILED"
            if "FAILED" in agent_statuses + science_statuses
            else "BLOCKED"
            if any(s != "SUCCEEDED" for s in agent_statuses + science_statuses)
            else "COMPLETED"
        )
        if not integrity or not bundle["ledger_integrity"]["verified"]:
            status = "FAILED"
        bundle.update(
            {
                "status": status,
                "agents": self.results,
                "handoffs": self.handoffs,
                "redesigns": self.redesigns,
                "registered_artifacts_verified": integrity,
                # Every worker emits a receipt, including blocked workers. Receipts
                # cannot establish that a scientific candidate was produced.
                "acceptance": acceptance_report(
                    {
                        **bundle,
                        "artifacts": [
                            a for a in bundle["artifacts"] if a.get("role") != "tool_receipt"
                        ],
                    }
                ),
                "scientific_review": "REQUIRED",
                "scope": (
                    "Dockshift/Nebius execution receipts; "
                    "completion is not experimental validation."
                ),
                "llm_agents_invoked": sum(r["llm_inference_calls"] > 0 for r in self.results),
                "compute_enabled": self.science.settings.agent_compute_enabled,
                "workflow": self.science.request.workflow,
                "candidate_screening_status": "COMPLETED"
                if self.science.verified_outputs.get("admet")
                else "BLOCKED",
                "candidate_name": self.science.request.candidate_name,
                "outputs": self.science.verified_outputs,
                "review_provider": "nebius"
                if self.science.request.use_nebius_llm
                and self.science.request.workflow != "preparation"
                else None,
            }
        )
        bundle = self.redact(bundle)
        self.trace.emit("run_terminal", status=status)
        self.write("agent_handoffs.json", self.handoffs)
        self.write("redesign_history.json", self.redesigns)
        self.write("report.json", bundle)
        manifest = {
            str(p.relative_to(self.out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.out.iterdir()
            if p.is_file() and p.name != "progress.json"
        }
        self.write("manifest.json", manifest)
        return bundle


def new_run_id():
    return "agents-" + uuid.uuid4().hex
