"""Bounded two-branch execution using Nebius and typed, hash-checked handoffs."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict

from .models import RemoteJob
from .remote import RemoteRunner, objects
from .scienceclaw.adapters.base import ToolFailed, ToolUnavailable
from .scienceclaw.contracts import AgentEvent, ArtifactRef, WorkerState
from .scientific_outputs import validate_output

ORDER = {"A1": 0, "A2": 1, "A3": 2, "A4": 3, "A5a": 4, "A5b": 5, "A6": 6, "A7": 7}
BRANCH_AGENTS = {"small_molecule": ("A3", "A5a"), "biologic": ("A4", "A5b")}


def pointer(document, path, value=None, write=False):
    keys = [k.replace("~1", "/").replace("~0", "~") for k in path[1:].split("/")]
    current = document
    for key in keys[:-1]:
        current = current[int(key)] if isinstance(current, list) else current[key]
    key = int(keys[-1]) if isinstance(current, list) else keys[-1]
    if write:
        current[key] = copy.deepcopy(value)
        return document
    return current[key]


def audit_plan(request):
    """Pure preflight; never constructs a client or submits computation."""
    from types import SimpleNamespace

    from .tools import ROLE_TOOLS

    ids, previous, findings = {"target": SimpleNamespace(branch="shared", agent="A1")}, -1, []
    for step in request.steps:
        if step.id in ids:
            raise ValueError("Scientific step IDs must be unique")
        if ORDER[step.agent] < previous:
            raise ValueError("Steps must follow agent dependency order")
        previous = ORDER[step.agent]
        if step.job.tool not in ROLE_TOOLS[step.agent] and not (
            step.agent == "A2" and step.job.tool == "use_prepared_structure"
        ):
            raise ValueError("Scientific tool is not bound to this agent")
        expected_branch = (
            "small_molecule"
            if step.agent in ("A3", "A5a")
            else "biologic"
            if step.agent in ("A4", "A5b")
            else None
        )
        if expected_branch and step.branch != expected_branch:
            raise ValueError("Scientific step is assigned to the wrong branch")
        if step.branch != "shared" and step.branch not in request.branches:
            raise ValueError("Step targets an unrequested branch")
        for binding in step.bindings:
            if binding.step not in ids:
                raise ValueError("Bindings must reference a preceding step")
            parent = ids[binding.step]
            if parent.branch not in ("shared", step.branch):
                raise ValueError("Cross-branch artifact substitution is forbidden")
        ids[step.id] = step
    for branch in request.branches:
        for agent in (*BRANCH_AGENTS[branch], "A6"):
            if not any(s.agent == agent and s.branch == branch for s in request.steps):
                findings.append(
                    {"agent": agent, "branch": branch, "code": "REVIEWED_STEP_REQUIRED"}
                )
    if not any(s.agent == "A2" for s in request.steps):
        findings.append({"agent": "A2", "branch": "shared", "code": "REVIEWED_STRUCTURE_REQUIRED"})
    return {
        "workflow": "collective",
        "submission_performed": False,
        "steps": len(request.steps),
        "missing": findings,
        "budget": request.budget.model_dump(),
        "live_verification": "NOT_RUN",
        "status": "BLOCKED"
        if findings or request.budget.max_submissions == 0
        else "PREPARED_REVIEW_REQUIRED",
    }


class CollectiveWorkflow:
    def __init__(self, tools):
        self.t = tools
        self.records = {}
        self.submissions = 0
        self.plan = audit_plan(tools.request)
        tools.verified_outputs["collective"] = {"plan": self.plan, "steps": {}, "branches": {}}
        self.output = tools.verified_outputs["collective"]
        self.prior = {}
        if tools.request.source_run:
            from .service import IntegrationService

            source = IntegrationService(
                tools.settings, tools.literature, tools.qsar, tools.structural, tools.nebius
            )
            report = source.report(tools.request.source_run)
            if report.get("workflow") != "collective":
                raise ValueError("Source run must use the collective workflow")
            self.prior = report.get("outputs", {}).get("collective", {}).get("steps", {})
            for key, row in self.prior.items():
                ref = row.get("typed_artifact")
                if row.get("status") == "SUCCEEDED" and ref and ArtifactRef(**ref).verify():
                    self.records[key] = ref

    def publish(self, step, value, inputs=()):
        path = self.t.out / f"{step.id}_typed.json"
        value["native_artifacts"] = self.output["steps"].get(step.id, {}).get("artifacts", [])
        record = {
            "schema": "dockshift-scientific-artifact/v1",
            "step": step.id,
            "agent": step.agent,
            "branch": step.branch,
            "provider": value.get("provider", "nebius"),
            "data": value,
            "input_sha256": list(inputs),
        }
        from .artifact_contracts import encode_artifact

        with path.open("x") as handle:
            json.dump(self.t.redact(encode_artifact(record)), handle, indent=2, allow_nan=False)
        ref = ArtifactRef.of(path, value["kind"])
        self.t.ledger.append(
            AgentEvent(
                run_id=self.t.run_id,
                agent=step.agent + "." + step.id,
                event_type="TYPED_SCIENTIFIC_ARTIFACT",
                status=WorkerState.SUCCEEDED,
                outputs=[ref],
                input_artifact_hashes=list(inputs),
                tool_versions={value["model_id"]: value["model_version"]},
                note=(
                    "Native output passed declared format/identity checks; scientific "
                    "and experimental review remain separate."
                ),
            )
        )
        self.records[step.id] = asdict(ref)
        return asdict(ref)

    def bind(self, step):
        arguments, hashes = copy.deepcopy(step.job.arguments), []
        for binding in step.bindings:
            ref = self.records.get(binding.step)
            if not ref:
                raise ToolUnavailable(
                    "UPSTREAM_TYPED_ARTIFACT_REQUIRED", "A required scientific handoff is missing."
                )
            if not ArtifactRef(**ref).verify():
                raise ToolFailed("HANDOFF_HASH_MISMATCH", "Upstream typed artifact changed.")
            document = json.loads(ArtifactRef(**ref).resolve().read_text())
            if step.agent == "A5a" and not step.acceptance.get("control"):
                if (
                    document.get("data", {}).get("kind") != "molecules"
                    or binding.argument != "/ligand"
                ):
                    # Receptor bindings are allowed, but a candidate binding must supply the ligand.
                    if document.get("data", {}).get("kind") == "molecules":
                        raise ToolUnavailable(
                            "LIGAND_BINDING_REQUIRED",
                            "Bind the actual generated SMILES to the native ligand argument.",
                        )
            pointer(arguments, binding.argument, pointer(document, binding.pointer), write=True)
            hashes.append(ref["sha256"])
        return arguments, hashes

    def check_inputs(self, step, arguments):
        from .scientific_inputs import check_step_inputs

        check_step_inputs(self, step, arguments)

    def admit(self, step, arguments):
        if step.job.operation_id or self.t.request.resume_operations.get(step.id):
            return
        budget = self.t.request.budget
        if not self.t.settings.agent_compute_enabled or not budget.approved_by:
            raise ToolUnavailable(
                "COMPUTE_APPROVAL_REQUIRED", "Collective scientific submission is disabled."
            )
        if self.submissions >= budget.max_submissions:
            raise ToolUnavailable(
                "SUBMISSION_BUDGET_EXHAUSTED", "No authorized submissions remain."
            )
        if (
            step.job.tool == "molmim_run_native"
            and arguments.get("particles", 2) * arguments.get("iterations", 1) > budget.max_decodes
        ):
            raise ToolUnavailable("DECODE_BUDGET_EXCEEDED", "MolMIM decode count exceeds budget.")
        for node in objects(arguments):
            if node.get("num_replicates", 1) * node.get("batch_size", 1) > budget.max_designs:
                raise ToolUnavailable(
                    "DESIGN_BUDGET_EXCEEDED", "Replicate/batch product exceeds reviewed budget."
                )
            if node.get("max_wall_seconds", 0) > budget.max_wall_seconds:
                raise ToolUnavailable("WALLTIME_BUDGET_EXCEEDED", "Native walltime exceeds budget.")
            for name in ("num_molecules",):
                if node.get(name, 1) > budget.max_molecules:
                    raise ToolUnavailable(
                        "MOLECULE_BUDGET_EXCEEDED", "Molecule count exceeds reviewed budget."
                    )
            for name in (
                "num_designs",
                "num_samples",
                "num_seq_per_target",
                "num_replicates",
                "sample_count",
            ):
                if node.get(name, 1) > budget.max_designs:
                    raise ToolUnavailable(
                        "DESIGN_BUDGET_EXCEEDED", "Design count exceeds reviewed budget."
                    )
        if step.agent == "A6":
            from .md_execution import expected_step_counts

            review = step.md_review
            if not review:
                raise ToolUnavailable(
                    "MD_SYSTEM_REVIEW_REQUIRED", "A branch-specific reviewed MD system is required."
                )
            path = self.t.structural.store.resolve_input(review.manifest.path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != review.manifest_sha256:
                raise ToolFailed("MD_MANIFEST_HASH_MISMATCH", "MD manifest changed.")
            counts = expected_step_counts(
                json.loads(path.read_text()), arguments, self.t.structural.store
            )
            if sum(counts.values()) > budget.max_md_steps:
                raise ToolUnavailable(
                    "MD_BUDGET_EXCEEDED", "Native dynamics steps exceed reviewed budget."
                )
        self.submissions += 1

    async def run_step(self, step):
        prior = self.prior.get(step.id, {})
        if step.id in self.records:
            # Reuse only an identical step specification, not a same-named new experiment.
            import_request = self.t.settings.agent_artifact_root
            if not import_request.is_absolute():
                from app.config import BACKEND_DIR

                import_request = BACKEND_DIR / import_request
            original = json.loads(
                (import_request / self.t.request.source_run / "request.json").read_text()
            )
            old_step = next((s for s in original.get("steps", []) if s["id"] == step.id), None)
            if old_step != step.model_dump(mode="json"):
                raise ToolUnavailable(
                    "SOURCE_STEP_CHANGED",
                    "Reviewed step differs from the sealed source experiment.",
                )
            self.output["steps"][step.id] = {**prior, "reused_from": self.t.request.source_run}
            return {
                "typed_artifact": self.records[step.id]
            }, "Verified immutable prior result reused."
        if self.t.request.resume_only and not (
            step.job.operation_id or self.t.request.resume_operations.get(step.id)
        ):
            raise ToolUnavailable(
                "RESUME_SUBMISSION_FORBIDDEN",
                (
                    "Resume only polls recorded operations; review a new continuation "
                    "to submit later stages."
                ),
            )
        required = {"A5a": "A3", "A5b": "A4"}.get(step.agent)
        if required and not any(
            s.agent == required and s.id in self.records for s in self.t.request.steps
        ):
            raise ToolUnavailable(
                "UPSTREAM_TYPED_ARTIFACT_REQUIRED",
                "The branch has no verified generated candidate.",
            )
        if step.agent in ("A3", "A4") and not any(
            s.agent == "A2" and s.id in self.records for s in self.t.request.steps
        ):
            raise ToolUnavailable(
                "UPSTREAM_STRUCTURE_REQUIRED", "A verified target structure is required."
            )
        if (
            required
            and not step.acceptance.get("control")
            and not any(
                b.step in self.records
                and next(s for s in self.t.request.steps if s.id == b.step).agent == required
                for b in step.bindings
            )
        ):
            raise ToolUnavailable(
                "CANDIDATE_BINDING_REQUIRED",
                "Downstream inputs must bind the actual upstream candidate.",
            )
        arguments, hashes = self.bind(step)
        if step.job.tool == "use_prepared_structure":
            if not step.acceptance.get("reviewed_by") or not step.acceptance.get(
                "unresolved_regions_review"
            ):
                raise ToolUnavailable(
                    "STRUCTURE_REVIEW_REQUIRED",
                    "Review the deposited construct and unresolved regions before using it.",
                )
            from .scientific_outputs import read_structure
            from .service import IntegrationService

            source = IntegrationService(
                self.t.settings, self.t.literature, self.t.qsar, self.t.structural, self.t.nebius
            )
            preparation_id = arguments.get("preparation_id", "")
            report = source.report(preparation_id)
            if (
                report.get("outputs", {}).get("structural_sources", {}).get("target_accession")
                != "O14746"
            ):
                raise ToolUnavailable(
                    "PRIMARY_STRUCTURE_REQUIRED", "Prepared source does not verify human hTERT."
                )
            path = source.artifact(preparation_id, "receptor_htert.pdb")
            text = path.read_text()
            info, _, _ = read_structure(text)
            value = {
                "kind": "structure",
                "provider": "rcsb",
                "model_id": "rcsb-9Q14",
                "model_version": hashlib.sha256(path.read_bytes()).hexdigest(),
                "structures": [{**info, "structure": text, "filename": "receptor_htert.pdb"}],
                "source_preparation_id": preparation_id,
                "unresolved_regions_review": step.acceptance["unresolved_regions_review"],
                "limitations": [
                    (
                        "Deposited observed chain only; unobserved residues are not modele"
                        "d. MD repair and assembly review remain required."
                    )
                ],
            }
            ref = self.publish(step, value, [value["model_version"]])
            self.output["steps"][step.id] = {
                "agent": "A2",
                "branch": "shared",
                "tool": step.job.tool,
                "status": "SUCCEEDED",
                "validation": value,
                "typed_artifact": ref,
            }
            return {
                "typed_artifact": ref
            }, "Reviewed experimental coordinates imported with verified provenance."

        hashes.append(hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest())
        self.check_inputs(step, arguments)
        self.admit(step, arguments)
        operation_id = step.job.operation_id or self.t.request.resume_operations.get(step.id)
        job = RemoteJob(tool=step.job.tool, arguments=arguments, operation_id=operation_id)
        if step.agent == "A6":
            from .md_execution import execute_md

            result, detail = await execute_md(self.t, job, label=step.id, review=step.md_review)
            self.output["steps"][step.id] = {
                "agent": step.agent,
                "branch": step.branch,
                **self.t.verified_outputs.get("md_branches", {}).get(step.id, {}),
            }
            return result, detail
        runner = RemoteRunner(self.t.settings, self.t.nebius.client, self.t.out, self.t.run_id)
        result = await runner.execute(step.id, job.tool, arguments, operation_id)
        self.output["steps"][step.id] = {"agent": step.agent, "branch": step.branch, **result}
        if result["status"] == "PENDING":
            raise ToolUnavailable(
                "REMOTE_OPERATION_PENDING", "Nebius operation is pending; resume polls it."
            )
        from .artifact_io import expand_archives

        expand_archives(result, self.t.out, self.t.settings.agent_max_artifact_bytes, self.t.redact)
        if step.agent == "A5a":
            from .scientific_inputs import docking_reference
            from .scientific_preparation import validate_diffdock

            path = docking_reference(self, step.acceptance)
            reference = path is not None
            value = validate_diffdock(
                result,
                arguments["ligand"],
                path,
                receptor=arguments.get("protein"),
                pocket_center=step.acceptance.get("pocket_center"),
            )
            if reference and value["reference_redocking_qc"] != "PASS":
                raise ToolFailed("DOCKING_REFERENCE_QC_FAILED", "Redocking failed reference QC.")
            from .scientific_outputs import documents, model_version

            value.update(
                kind="docking",
                model_id="diffdock",
                model_version=model_version(documents(result), "diffdock"),
            )
        else:
            value = validate_output(
                job.tool,
                result,
                {
                    **step.acceptance,
                    "_step_id": step.id,
                    "requested_molecules": arguments.get("num_molecules", 1),
                    "requested_designs": arguments.get("num_seq_per_target", 1),
                },
                self.t.out,
            )
        if step.agent == "A3":
            smiles = [m["smiles"] for m in value.get("molecules", [])]
            if smiles:
                prediction = await self.t.qsar.predict_activity(smiles)
                profile = await self.t.qsar.profile(smiles)
                value["dockshift_qsar"] = prediction.model_dump(mode="json")
                value["dockshift_profiles"] = profile.model_dump(mode="json")
                value["limitations"].append(
                    "hTERT QSAR predictions are not measured inhibition; applicability"
                    " domain must be inspected."
                )
        ref = self.publish(step, value, hashes)
        self.output["steps"][step.id].update(
            validation=value, typed_artifact=ref, status="SUCCEEDED"
        )
        return {"typed_artifact": ref}, "Native scientific output and typed handoff verified."

    async def dispatch(self, agent):
        if agent == "A1":
            from .candidate import CandidateWorkflow

            result, detail = await CandidateWorkflow(self.t).identity()
            from .artifact_contracts import encode_artifact

            path = self.t.out / "target_typed.json"
            target = self.t.verified_outputs["target"]
            record = encode_artifact(
                {
                    "schema": "dockshift-scientific-artifact/v1",
                    "step": "target",
                    "agent": "A1",
                    "branch": "shared",
                    "provider": "uniprot",
                    "data": {
                        "kind": "target",
                        "model_id": "uniprot",
                        "model_version": target["source_sha256"],
                        **target,
                    },
                    "input_sha256": [target["source_sha256"]],
                }
            )
            path.write_text(json.dumps(record, indent=2))
            self.records["target"] = asdict(ArtifactRef.of(path, "target_identity"))
            return result, detail
        if agent == "A7":
            branches = {}
            for branch in self.t.request.branches:
                rows = [s for s in self.t.request.steps if s.branch == branch]
                missing = [
                    a for a in (*BRANCH_AGENTS[branch], "A6") if not any(s.agent == a for s in rows)
                ]
                branches[branch] = {
                    "status": "COMPLETED"
                    if rows
                    and not missing
                    and all(
                        self.output["steps"].get(s.id, {}).get("status") == "SUCCEEDED"
                        for s in rows
                    )
                    else "BLOCKED",
                    "missing_agents": missing,
                    "steps": [s.id for s in rows],
                    "scientific_acceptance": "SCIENTIST_REVIEW_REQUIRED",
                }
            self.output["branches"] = branches
            return await self.t.dispatch_advanced("A7")
        steps = [s for s in self.t.request.steps if s.agent == agent]
        if not steps:
            raise ToolUnavailable(
                "REVIEWED_STEP_REQUIRED", "No reviewed collective scientific step supplied."
            )
        receipts = []
        for step in steps:
            try:
                result, detail = await self.run_step(step)
                status = result.pop("_status", "SUCCEEDED")
                receipts.append(
                    {"step": step.id, "status": status, "result": result, "detail": detail}
                )
            except ToolUnavailable as exc:
                receipts.append(
                    {
                        "step": step.id,
                        "status": "BLOCKED",
                        "code": exc.error_code,
                        "detail": exc.detail,
                    }
                )
            except ToolFailed as exc:
                receipts.append(
                    {
                        "step": step.id,
                        "status": "FAILED",
                        "code": exc.error_code,
                        "detail": exc.detail,
                    }
                )
            except Exception:
                receipts.append(
                    {
                        "step": step.id,
                        "status": "FAILED",
                        "code": "SCIENTIFIC_VALIDATION_FAILED",
                        "detail": "Native execution or validation failed.",
                    }
                )
            self.output["steps"].setdefault(step.id, {}).update(
                {k: v for k, v in receipts[-1].items() if k != "result"}
            )
        status = (
            "FAILED"
            if any(r["status"] == "FAILED" for r in receipts)
            else "BLOCKED"
            if any(r["status"] == "BLOCKED" for r in receipts)
            else "SUCCEEDED"
        )
        return {
            "steps": receipts,
            "_status": status,
            **({"_error_code": "COLLECTIVE_STEP_INCOMPLETE"} if status != "SUCCEEDED" else {}),
        }, "Branch-specific execution receipts; no result substituted for missing science."
