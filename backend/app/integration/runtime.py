"""Dockshift binding of the existing eight-worker tool-calling runtime."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import asdict, replace

from .privacy import Redactor
from .scienceclaw.contracts import ArtifactRef
from .scienceclaw.report.export import acceptance_report, build_bundle
from .scienceclaw.runtime.engine import SPECS, AgentRuntime, Trace
from .scienceclaw.runtime.llm import OllamaProvider

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
            OllamaProvider() if science.request.use_local_llm else DisabledProvider()
        )
        self.probe = self.provider.probe()
        self.registry, self.latest = {}, {}
        self.results, self.handoffs, self.redesigns = [], [], []
        self.max_cycles = 0
        self.methods = {s.agent_id: self.bind(s.agent_id) for s in SPECS}
        for spec in SPECS:
            self.trace.emit("agent_initialized", spec.agent_id, specification=asdict(spec))

    def write(self, name, data):
        return super().write(name, self.redact(data))

    def bind(self, agent):
        def execute():
            return asyncio.run_coroutine_threadsafe(self.science.execute(agent), self.loop).result()

        return execute

    def run(self):
        for spec in SPECS:
            self.invoke(spec, 0)
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
            if p.is_file()
        }
        self.write("manifest.json", manifest)
        return bundle


def new_run_id():
    return "agents-" + uuid.uuid4().hex
