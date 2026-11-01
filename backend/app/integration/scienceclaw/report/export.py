"""Deterministic evidence adjudication and export (spec 12.4 step 8, 14.2).

Every displayed value is read back out of the ledger, which in turn only holds
values an agent received from a tool. The exporter has no arithmetic of its own
and cannot introduce a number.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts import EvidenceState, MetricStatus, WorkerState
from ..ledger import AppendOnlyLedger

#: Experiments that must be done before any anticancer claim (spec 11).
VALIDATION_PATHWAY = [
    {
        "step": 1,
        "name": "Target relevance",
        "requirement": "evidence linking the human protein to the selected tumour context "
        "and the proposed mechanism of intervention",
    },
    {
        "step": 2,
        "name": "Biochemical target engagement",
        "requirement": "binding or functional inhibition measured on the correctly "
        "identified human target, with defined units, conditions and controls",
    },
    {
        "step": 3,
        "name": "Cancer-cell activity",
        "requirement": "cell-based measurement of target pathway effect and tumour-cell "
        "viability or proliferation, with controls for non-specific toxicity",
    },
    {
        "step": 4,
        "name": "Selectivity",
        "requirement": "target-family, off-target and non-tumour cell comparisons; "
        "not interchangeable with docking scores",
    },
    {
        "step": 5,
        "name": "Delivery and exposure",
        "requirement": "uptake, stability and intracellular processing for small molecules; "
        "extracellular accessibility or justified delivery for biologics",
    },
    {
        "step": 6,
        "name": "Preclinical progression",
        "requirement": "pharmacology, toxicity, pharmacokinetics and model-specific efficacy, "
        "outside this computational scope",
    },
]


def build_bundle(ledger: AppendOnlyLedger, run_id: str) -> dict:
    """Assemble the final artifact bundle from ledger records only."""
    chain_ok, chain_error = ledger.verify()
    events = ledger.events()

    computational_evidence = []
    unresolved = []
    for event in events:
        if event["status"] == WorkerState.SUCCEEDED.value:
            for metric in event.get("metrics", []):
                if metric["status"] == MetricStatus.COMPUTED.value:
                    computational_evidence.append(
                        {
                            "agent": event["agent"],
                            "candidate_id": event.get("candidate_id"),
                            "metric": metric["name"],
                            "value": metric["value"],
                            "unit": metric["unit"],
                            "method": metric["method"],
                            "event_id": event["event_id"],
                        }
                    )
        elif event["status"] in (WorkerState.BLOCKED.value, WorkerState.FAILED.value):
            unresolved.append(
                {
                    "agent": event["agent"],
                    "status": event["status"],
                    "error_code": event["error_code"],
                    "detail": event.get("note"),
                    "event_id": event["event_id"],
                }
            )

    artifacts = [{"agent": e["agent"], **o} for e in events for o in e.get("outputs", [])]

    return {
        "run_id": run_id,
        "ledger_integrity": {"verified": chain_ok, "error": chain_error},
        "evidence_state_of_all_candidates": EvidenceState.EXPERIMENT_REQUIRED.value,
        "computational_evidence": computational_evidence,
        "unresolved_and_blocked": unresolved,
        "artifacts": artifacts,
        "required_experiments": VALIDATION_PATHWAY,
        "separation_statement": (
            "Computational evidence above is the output of named scoring functions, "
            "simulations and structure predictors under the recorded configurations. "
            "None of it establishes human-target inhibition, anticancer activity, "
            "clinical efficacy or safety. Those outcomes are assigned to the experiments "
            "listed under required_experiments, and every candidate here remains a "
            "research hypothesis until a suitable assay measures its function."
        ),
    }


def write_bundle(ledger: AppendOnlyLedger, run_id: str, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "evidence_bundle.json"
    path.write_text(json.dumps(build_bundle(ledger, run_id), indent=2), encoding="utf-8")
    return path


def acceptance_report(bundle: dict) -> dict:
    """Score the run against the deliverable acceptance criteria (spec 13.2)."""
    agents_with_artifacts = {a["agent"] for a in bundle["artifacts"]}
    has_molecule = any(a.startswith("A3") for a in agents_with_artifacts)
    has_binder = any(a.startswith("A4") for a in agents_with_artifacts)
    has_docking = any(e["agent"].startswith("A5a") for e in bundle["computational_evidence"])
    has_md = any(e["agent"].startswith("A6") for e in bundle["computational_evidence"])
    has_challenge = any(a.startswith("A7") for a in agents_with_artifacts)
    md_blocked = any(e["agent"].startswith("A6") for e in bundle["unresolved_and_blocked"])
    # MD evidence only counts when it came from a system that cleared the gate,
    # which the dynamics agent signals by emitting a ligand RMSD at all.
    md_gate_passed = any(
        e["agent"].startswith("A6") and e["metric"].startswith("ligand_rmsd")
        for e in bundle["computational_evidence"]
    )

    # Each criterion reports one of the states in the master guide section 13.3.
    # "NOT_RUN" is never collapsed into a pass: a calculation that did not
    # happen cannot satisfy a criterion about its quality.
    criteria = {
        "both_branches_produced_candidates": (
            "PASS"
            if (has_molecule and has_binder)
            else "NOT_RUN"
            if not (has_molecule or has_binder)
            else "FAIL"
        ),
        "real_human_target_docking_exported": "PASS" if has_docking else "NOT_RUN",
        "md_executed_on_validated_system": (
            "PASS"
            if (has_md and md_gate_passed)
            else "BLOCKED"
            if md_blocked
            else "FAIL"
            if has_md
            else "NOT_RUN"
        ),
        "challenge_or_abstention_recorded": "PASS" if has_challenge else "NOT_RUN",
        "all_values_read_from_artifacts": (
            "PASS" if bundle["ledger_integrity"]["verified"] else "FAIL"
        ),
        "conclusions_separated_from_experiments": (
            "PASS" if bundle["required_experiments"] else "FAIL"
        ),
    }
    return {
        "criteria": criteria,
        "complete_at_declared_scope": all(v == "PASS" for v in criteria.values()),
        "state_legend": {
            "PASS": "the required evidence exists and met its criterion",
            "FAIL": "the computation ran and did not meet its criterion",
            "NOT_RUN": "the computation was never performed",
            "BLOCKED": "missing inputs, tools or parameters prevented the computation",
        },
        "note": (
            "A criterion that is NOT_RUN or BLOCKED is not a pass. That is the honest "
            "state of the run, not a defect to be papered over."
        ),
    }
