"""Real, read-only hTERT/BIBR1532 tool path for the eight-agent website demo.

No model submissions, design generation, docking, folding, ADMET or MD. Local
QSAR/chemistry and primary-record/schema reads are the only scientific work.
"""

import json

from app.nebius.service import _unwrap

from .candidate import CandidateWorkflow
from .models import RunRequest
from .scienceclaw.adapters.base import ToolUnavailable
from .scientific_preparation import ScientificPreparation

DEMO_TOOLS = {
    "A1": "verify_htert_sources",
    "A2": "audit_htert_structure",
    "A3": "screen_bibr1532",
    "A4": "preflight_biologic_design",
    "A5a": "prepare_diffdock_inputs",
    "A5b": "preflight_protein_complex",
    "A6": "audit_md_prerequisites",
    "A7": "inspect_research",
}


def demo_request():
    return RunRequest(
        workflow="demonstration",
        candidate_name="BIBR1532",
        compounds=["BIBR1532"],
        target={
            "label": "hTERT",
            "species": "Homo sapiens",
            "accession": "O14746",
            "structure_id": "9Q14",
            "structure_kind": "experimental",
        },
        remote_admet=False,
        docking=False,
        use_llm=True,
        llm_provider="anthropic",
        budget={
            "max_submissions": 0,
            "max_llm_calls": 24,
            "max_llm_cost_usd": 0.10,
            "approved_by": "User-approved bounded website demonstration",
        },
    )


class DemonstrationWorkflow:
    def __init__(self, tools):
        self.t = tools
        self.preparation = ScientificPreparation(tools)
        self.candidate = CandidateWorkflow(tools)
        self.summaries = {}

    async def schemas(self, agent, models):
        discovered = {t.name: t for t in await self.t.nebius.client.list_tools()}
        rows = []
        for tool, model in models:
            if tool not in discovered:
                raise ToolUnavailable(
                    "NEBIUS_TOOL_UNAVAILABLE",
                    "Nebius does not advertise the requested scientific tool.",
                )
            meta = _unwrap(
                await self.t.nebius.client.call(
                    "get_model_schema", {"model_id": model, "summary_only": True}
                )
            )
            row = {
                "tool": tool,
                "model": model,
                "discovered": True,
                "reported_qualification": meta.get("qualification") or meta.get("readiness"),
                "input_schema": discovered[tool].input_schema,
                "execution": "NOT_RUN",
            }
            rows.append(row)
        path = self.t.out / (agent + "_discovered_contracts.json")
        with path.open("x") as handle:
            json.dump(self.t.redact(rows), handle, indent=2)
        self.t.verified_outputs[agent + "_contracts"] = rows
        return [
            {
                "tool": r["tool"],
                "reported_qualification": r["reported_qualification"],
                "execution": "NOT_RUN",
            }
            for r in rows
        ]

    async def dispatch(self, agent):
        if self.t.settings.agent_compute_enabled or self.t.settings.agent_admet_enabled:
            raise ToolUnavailable(
                "DEMO_COMPUTE_MUST_BE_DISABLED",
                "Demonstration refuses enabled scientific computation.",
            )
        if agent == "A1":
            identity, detail = await self.candidate.identity()
            sources, _ = await self.preparation.dispatch("A1")
            summary = {
                "target": "human hTERT",
                "accession": "O14746",
                "structure": "9Q14",
                "primary_identity_verified": True,
                "source_hashes": sources["source_hashes"],
            }
            payload = {"identity": identity, "sources": sources}
        elif agent == "A2":
            payload, detail = await self.preparation.dispatch("A2")
            models = await self.schemas(agent, [("infer_openfold3_native", "openfold3")])
            summary = {
                "observed_residues": payload["observed_residues"],
                "unresolved_ranges": payload["internal_residue_number_gaps"],
                "folding_execution": "NOT_RUN",
                "available_models": models,
            }
        elif agent == "A3":
            await self.preparation.dispatch("A3")
            payload, detail = await self.candidate.screen()
            rows = payload["qsar"]["predictions"]
            summary = {
                "input": "BIBR1532",
                "predictions": rows,
                "scope": (
                    "Existing local Dockshift QSAR prediction; not an assay or molecule generation."
                ),
                "admet_execution": "NOT_RUN",
            }
        elif agent == "A4":
            models = await self.schemas(
                agent,
                [
                    ("infer_proteinmpnn_native", "proteinmpnn"),
                    ("submit_rfdiffusion", "rfdiffusion"),
                ],
            )
            summary = {
                "available_models": models,
                "binder_generated": False,
                "missing": [
                    "Reviewed exposed epitope/scaffold and chain mapping",
                    "Scientific-compute approval",
                ],
                "limitation": "Intracellular/nuclear hTERT delivery for biologics is unresolved.",
            }
            payload = {
                "_status": "BLOCKED",
                "_error_code": "BIOLOGIC_DESIGN_NOT_EXECUTED",
                **summary,
            }
            detail = "Real Nebius design contracts inspected. No binder was generated."
        elif agent == "A5a":
            payload, detail = await self.preparation.dispatch("A5a")
            payload = {**payload, "_status": "BLOCKED", "_error_code": "DOCKING_COMPUTE_DISABLED"}
            summary = {
                "input_schema_valid": payload["schema_valid"],
                "receptor_sha256": payload["receptor_sha256"],
                "reference_sdf_sha256": payload["reference_sdf_sha256"],
                "docking_execution": "NOT_RUN",
                "docking_score": None,
                "review_required": payload["review_required"],
            }
        elif agent == "A5b":
            models = await self.schemas(
                agent, [("boltz2_predict_native", "boltz2"), ("submit_alphafold3", "alphafold3")]
            )
            summary = {
                "available_models": models,
                "complex_prediction": "NOT_RUN",
                "confidence": None,
                "missing": ["Actual designed binder from A4", "Compute approval"],
                "limitation": "Model confidence is not evidence of binding or inhibition.",
            }
            payload = {
                "_status": "BLOCKED",
                "_error_code": "COMPLEX_PREDICTION_NOT_EXECUTED",
                **summary,
            }
            detail = (
                "Real Nebius complex-prediction contracts inspected; no compl"
                "ex or confidence fabricated."
            )
        elif agent == "A6":
            payload, detail = await self.preparation.dispatch("A6")
            summary = {
                "protocol_schemas_valid": payload["protocols_schema_valid"],
                "missing": payload["missing"],
                "simulation_execution": "NOT_RUN",
                "convergence": "NOT_ASSESSED",
            }
        else:
            payload, detail = await self.t.dispatch_advanced("A7")
            summary = self.t.verified_outputs["review"]
        self.summaries[agent] = summary
        self.t.verified_outputs.setdefault("demonstration", {})[agent] = summary
        return {**payload, "demonstration_summary": summary}, detail
