"""Connected one-candidate workflow, reusing Dockshift's scientific services."""

import hashlib
import json
import math
from dataclasses import asdict
from importlib.metadata import version

from app.literature.models import SearchRequest
from app.nebius.receptor import ensure_receptor, receptor_for, sites

from .remote import RemoteRunner, objects
from .scienceclaw.adapters.base import ToolUnavailable
from .scienceclaw.adapters.chemistry import RDKitAdapter
from .scienceclaw.contracts import AgentEvent, ArtifactRef, Channel, Metric, WorkerState


class CandidateWorkflow:
    def __init__(self, tools):
        self.tools = tools
        self.request = tools.request
        self.outputs = tools.verified_outputs
        self.remote = RemoteRunner(tools.settings, tools.nebius.client, tools.out, tools.run_id)

    def save(self, name, data):
        with (self.tools.out / name).open("x") as f:
            json.dump(self.tools.redact(data), f, indent=2, allow_nan=False)

    async def dispatch(self, agent):
        if agent == "A1":
            return await self.identity()
        if agent == "A2":
            if self.request.alignment:
                return await self.tools.dispatch_advanced(agent)
            capabilities = await self.tools.structural.capabilities()
            self.outputs["structural_capabilities"] = capabilities.model_dump(mode="json")
            return {
                "_status": "BLOCKED",
                "_error_code": "STRUCTURE_REVIEW_REQUIRED",
                "capabilities": self.outputs["structural_capabilities"],
            }, "No reviewed structure comparison supplied; QSAR/ADMET can proceed independently."
        if agent == "A3":
            return await self.screen()
        if agent == "A5a" and self.request.docking:
            return await self.dock()
        if agent in {"A4", "A5a", "A5b", "A6"}:
            # Existing advanced role bindings remain available for reviewed design/MD inputs.
            if agent in self.request.jobs:
                return await self.tools.dispatch_advanced(agent)
            raise ToolUnavailable(
                "REVIEWED_SCIENTIFIC_INPUT_REQUIRED",
                f"{agent} has no reviewed design, docking or MD inputs; no job submitted.",
            )
        return await self.tools.dispatch_advanced(agent)

    async def identity(self):
        if len(self.request.compounds) != 1:
            raise ToolUnavailable(
                "ONE_CANDIDATE_REQUIRED", "Candidate workflow accepts one compound."
            )
        if (
            self.request.target.label.lower() != "htert"
            or self.request.target.species != "Homo sapiens"
            or self.request.target.accession not in (None, "O14746")
        ):
            raise ToolUnavailable("TARGET_NOT_SUPPORTED", "This workflow supports human hTERT.")
        response = await self.tools.qsar.client.get(
            "https://rest.uniprot.org/uniprotkb/O14746.json"
        )
        response.raise_for_status()
        record = response.json()
        genes = [v.get("geneName", {}).get("value") for v in record.get("genes", [])]
        if (
            record.get("primaryAccession") != "O14746"
            or record.get("organism", {}).get("taxonId") != 9606
            or "TERT" not in genes
        ):
            raise ValueError("Primary source target identity mismatch")
        sequence = record.get("sequence", {}).get("value")
        if not sequence:
            raise ValueError("Primary source has no target sequence")
        raw = response.content
        with (self.tools.out / "A1_uniprot.json").open("xb") as f:
            f.write(raw)
        identity = {
            "accession": "O14746",
            "gene": "TERT",
            "species": "Homo sapiens",
            "source": str(response.url),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            "verification": "Primary accession, taxon and gene checked against live UniProt",
        }
        self.outputs["target"] = identity
        result = {"target": identity}
        if self.request.literature_query:
            literature = await self.tools.literature.search(
                SearchRequest(
                    query=self.request.literature_query, max_results_per_source=3, full_text="never"
                )
            )
            self.outputs["literature"] = literature.model_dump(mode="json")
            self.outputs["literature"]["retrieval_status"] = (
                "PARTIAL" if literature.errors else "COMPLETED"
            )
            result["literature"] = self.outputs["literature"]
        return (
            result,
            "Live human hTERT identity verified; literature source failures remain explicit.",
        )

    async def screen(self):
        t = self.tools
        query = self.request.compounds[0]
        prediction = await t.qsar.predict_activity([query])
        row = prediction.predictions[0]
        if row.error or not row.smiles or row.predicted_pic50 is None:
            raise ToolUnavailable(
                "CANDIDATE_NOT_RESOLVED", "Candidate has no validated QSAR prediction."
            )
        audit = RDKitAdapter().audit(row.smiles)
        if not audit.valid:
            raise ValueError("Resolved candidate failed chemical validation")
        profiles = await t.qsar.profile([row.smiles])
        model = await t.qsar.model_info()
        local = {
            "qsar": prediction.model_dump(mode="json"),
            "profiles": profiles.model_dump(mode="json"),
            "chemical_audit": asdict(audit),
            "model": model,
            "versions": {n: version(n) for n in ("rdkit", "xgboost", "numpy")},
            "input_sha256": hashlib.sha256(row.smiles.encode()).hexdigest(),
        }
        self.save("A3_qsar.json", local)
        self.outputs["screening"] = local
        # Local science remains available even when the mandatory remote stage is pending.
        t.ledger.append(
            AgentEvent(
                run_id=t.run_id,
                agent="A3.qsar",
                event_type="LOCAL_QSAR_COMPLETED",
                status=WorkerState.SUCCEEDED,
                target_accession="O14746",
                outputs=[ArtifactRef.of(t.out / "A3_qsar.json", "qsar_result")],
                channel=Channel.QSAR_PREDICTION,
                tool_versions=local["versions"],
                metrics=[
                    Metric.computed(
                        "predicted_pic50",
                        row.predicted_pic50,
                        "pIC50",
                        "Dockshift hTERT XGBoost; computational prediction",
                    )
                ],
            )
        )
        if not self.request.remote_admet:
            return {
                **local,
                "_status": "BLOCKED",
                "_error_code": "NEBIUS_SCIENCE_REQUIRED",
            }, "Local QSAR completed; required Nebius ADMET stage was not selected."
        if not (
            t.settings.agent_admet_enabled
            or t.settings.agent_compute_enabled
            or self.request.resume_operations.get("A3_admet")
        ):
            return {
                **local,
                "_status": "BLOCKED",
                "_error_code": "ADMET_APPROVAL_REQUIRED",
            }, "Local QSAR completed. Enable the one-candidate ADMET execution gate to proceed."
        remote = await self.remote.execute(
            "A3_admet",
            "infer_admet_ai_native",
            {
                "molecules": [{"id": "candidate-1", "smiles": row.smiles}],
                "endpoints": ["hERG", "AMES", "Solubility_AqSolDB"],
            },
            self.request.resume_operations.get("A3_admet"),
        )
        self.outputs["admet_operation"] = {k: v for k, v in remote.items() if k != "artifacts"}
        if remote["status"] != "SUCCEEDED":
            return {
                **local,
                "_status": "BLOCKED",
                "_error_code": "REMOTE_OPERATION_PENDING",
                "operation": remote,
            }, "QSAR completed; Nebius ADMET is pending, not completed."
        self.outputs["admet"] = self.validate_admet(remote, row.smiles)
        self.save("A3_admet_validation.json", self.outputs["admet"])
        admet = self.outputs["admet"]
        t.ledger.append(
            AgentEvent(
                run_id=t.run_id,
                agent="A3.admet",
                event_type="NEBIUS_ADMET_VERIFIED",
                status=WorkerState.SUCCEEDED,
                channel=Channel.ADMET_PREDICTION,
                outputs=[
                    ArtifactRef.of(t.out / a["filename"], "admet_result")
                    for a in remote["artifacts"]
                ],
                input_artifact_hashes=[local["input_sha256"]],
                tool_versions={"admet-ai": admet["model_version"]},
                metrics=[
                    Metric.computed(
                        endpoint["endpoint"],
                        endpoint["value"],
                        endpoint["units"],
                        "Nebius ADMET-AI "
                        + admet["model_version"]
                        + "; predicted "
                        + endpoint["task_type"],
                    )
                    for endpoint in admet["endpoints"]
                ],
            )
        )
        return (
            {**local, "admet": self.outputs["admet"]},
            "QSAR and Nebius ADMET outputs verified for this candidate; "
            "neither establishes efficacy.",
        )

    @staticmethod
    def validate_admet(remote, smiles):
        if not remote.get("artifacts") or not all(
            a.get("hash_verified") for a in remote["artifacts"]
        ):
            raise ToolUnavailable("ARTIFACT_UNVERIFIED", "ADMET artifact bytes were not verified.")
        documents = [
            a["data"] for a in remote["artifacts"] if a["data"].get("model_id") == "admet-ai"
        ]
        if len(documents) != 1:
            raise ToolUnavailable(
                "ADMET_SCHEMA_UNVERIFIED", "Expected one native ADMET-AI artifact."
            )
        document = documents[0]
        if document.get("status") != "succeeded" or document.get("molecule_count") != 1:
            raise ValueError("ADMET artifact is not a successful single-molecule result")
        if document.get("succeeded") != 1 or document.get("failed") != 0:
            raise ValueError("ADMET molecule counts are inconsistent with successful execution")
        rows = document.get("results", [])
        if len(rows) != 1 or rows[0].get("id") != "candidate-1":
            raise ValueError("ADMET result has an unexpected molecule identifier")
        row = rows[0]
        if row.get("input_smiles") != smiles or row.get("canonical_smiles") != smiles:
            raise ToolUnavailable(
                "ADMET_IDENTITY_UNVERIFIED", "ADMET molecule identity does not match."
            )
        if row.get("status") != "succeeded" or row.get("error"):
            raise ValueError("ADMET model reported a molecule error")
        metadata, endpoints = document.get("endpoint_metadata", {}), []
        for name in ("hERG", "AMES", "Solubility_AqSolDB"):
            value = row.get("predictions", {}).get(name)
            definition = metadata.get(name, {})
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("ADMET endpoint value missing or non-finite")
            if not all(definition.get(k) for k in ("units", "species", "task_type")):
                raise ToolUnavailable(
                    "ADMET_UNITS_REQUIRED", "Native endpoint metadata is incomplete."
                )
            if definition["task_type"] == "classification" and not 0 <= value <= 1:
                raise ValueError("Classification endpoint outside its expected score range")
            if definition["task_type"] not in {"classification", "regression"}:
                raise ValueError("ADMET endpoint task type is unsupported")
            endpoints.append({**definition, "endpoint": name, "value": value})
        if not document.get("model_version"):
            raise ToolUnavailable("MODEL_VERSION_REQUIRED", "ADMET version was not supplied.")
        return {
            "provider": "nebius",
            "tool": remote["tool"],
            "operation_id": remote["operation_id"],
            "model_version": document["model_version"],
            "validation": "Artifact SHA-256/size, native status, input/canonical identity, "
            "finite endpoint values, units and species verified",
            "endpoints": endpoints,
            "artifacts": remote["artifacts"],
            "limitations": document.get("limitations", [])
            + [
                "ADMET is target-independent prediction, not a human safety verdict.",
                "No measured binding, inhibition or clinical claim.",
            ],
        }

    async def dock(self):
        t = self.tools
        if not t.settings.agent_compute_enabled:
            raise ToolUnavailable(
                "COMPUTE_APPROVAL_REQUIRED", "Docking awaits expensive-compute approval."
            )
        row = self.outputs["screening"]["qsar"]["predictions"][0]
        # Reuse the teammate receptor preparation and exact known site; no new docking engine.
        await ensure_receptor(t.qsar.client, t.settings)
        site = sites()[0]
        receptor = receptor_for(site.centroid, 18.0)
        result = await self.remote.execute(
            "A5a_diffdock",
            "infer_diffdock_native",
            {
                "protein": receptor,
                "ligand": row["smiles"],
                "num_poses": 1,
            },
            self.request.resume_operations.get("A5a_diffdock"),
        )
        self.outputs["docking"] = result
        if result["status"] != "SUCCEEDED":
            return {
                "_status": "BLOCKED",
                "_error_code": "REMOTE_OPERATION_PENDING",
                **result,
            }, "Nebius docking pending; pose confidence is not affinity."
        poses = [
            v.get("ligand_positions")
            for a in result["artifacts"]
            for v in objects(a["data"])
            if v.get("ligand_positions")
        ]
        if not poses:
            raise ToolUnavailable(
                "DOCKING_POSES_UNVERIFIED", "No actual pose structures in verified artifacts."
            )
        return (
            result,
            "Nebius pose artifact verified; reference-pose and biological review still required.",
        )
