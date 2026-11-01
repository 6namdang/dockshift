"""Dockshift binding of the existing eight-worker tool-calling runtime."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import asdict, replace

from .anthropic_llm import AnthropicLLMProvider
from .llm_provider import requested_provider
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
        self.provider_name = requested_provider(science.settings, science.request)
        max_calls = (
            (science.request.budget.max_llm_calls if science.request.budget.approved_by else 0)
            if science.request.workflow in ("collective", "demonstration")
            else 64
        )
        if provider is not None:
            self.provider = provider
        elif self.provider_name == "anthropic":
            self.provider = AnthropicLLMProvider(
                science.settings,
                max_calls=max_calls,
                max_cost_usd=science.request.budget.max_llm_cost_usd,
            )
        elif self.provider_name == "nebius":
            self.provider = NebiusLLMProvider(science.settings, max_calls=max_calls)
        else:
            self.provider = DisabledProvider()
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
        if science.request.workflow == "demonstration":
            from .demonstration import DEMO_TOOLS

            self.specs = tuple(
                replace(
                    s,
                    tool=DEMO_TOOLS[s.agent_id],
                    instructions=s.instructions
                    + (
                        " This is a read-only demonstration. Inspect the real returned summary "
                        "and cite receipt hashes. Distinguish completed local audits from BLOCKED "
                        "scientific execution. Call conclude after the tool receipt unless one "
                        "evidence read is necessary."
                    ),
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
        prior, completed = None, set()
        if self.science.request.workflow == "demonstration" and self.science.request.source_run:
            from .demo_checkpoint import restore_demo

            prior, completed = restore_demo(self)
        for spec in self.specs:
            if spec.agent_id in completed:
                continue
            if self.science.request.workflow == "demonstration" and hasattr(
                self.provider, "begin_agent"
            ):
                self.provider.begin_agent(spec.agent_id)
            self.science.progress(spec.agent_id, "RUNNING")
            result = self.invoke(spec, 0)
            if prior:
                old = next(r for r in prior["agents"] if r["agent"] == spec.agent_id)
                result["prior_attempted_requests"] = prior["reasoning_usage"][
                    "per_agent_requests"
                ].get(spec.agent_id, 0)
                result["llm_validated_responses"] = result["llm_inference_calls"]
                result["prior_contract_errors"] = old["errors"]
                # A schema-validation error proves that a model response existed.
                invalid = sum("Additional properties are not allowed" in e for e in old["errors"])
                result["llm_inference_calls"] += old["llm_inference_calls"] + invalid

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
                "review_provider": self.provider_name,
                "reasoning_usage": {
                    "provider": self.provider_name,
                    "model": self.probe.get("model"),
                    "attempted_requests": getattr(self.provider, "calls", 0),
                    "reserved_cost_usd": str(getattr(self.provider, "reserved_usd", 0)),
                    "request_limit": getattr(self.provider, "max_calls", 0),
                    "cost_limit_usd": str(getattr(self.provider, "budget", 0)),
                    "per_agent_requests": getattr(self.provider, "agent_calls", {}),
                    "usage": getattr(self.provider, "usage", []),
                },
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
