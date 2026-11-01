"""Admission checks before any scientific submission (never inferred by the LLM)."""

import hashlib
import json

from .scienceclaw.adapters.base import ToolFailed, ToolUnavailable
from .scientific_outputs import read_structure, sequence


def check_step_inputs(workflow, step, arguments):
    acceptance = step.acceptance
    if not acceptance.get("reviewed_by"):
        raise ToolUnavailable(
            "SCIENTIFIC_REVIEW_REQUIRED", "Each scientific stage needs a named input reviewer."
        )
    tool = step.job.tool
    if step.agent in ("A2", "A5b"):
        chains = acceptance.get("chains")
        if not chains:
            raise ToolUnavailable(
                "EXPECTED_CHAINS_REQUIRED", "Review exact chain identities/sequences."
            )
        for seq in chains.values():
            sequence(seq)
        if step.agent == "A5b" and not acceptance.get("interface_chains"):
            raise ToolUnavailable(
                "INTERFACE_REVIEW_REQUIRED", "Review target/binder chain IDs and epitope."
            )
        supplied = []
        if tool == "infer_openfold2_native":
            supplied = [arguments.get("sequence")]
        elif tool == "infer_openfold3_native":
            supplied = [
                m.get("sequence")
                for i in arguments.get("inputs", [])
                for m in i.get("molecules", [])
            ]
        elif tool == "boltz2_predict_native":
            supplied = [
                m.get("sequence")
                for m in arguments.get("polymers", [])
                if m.get("molecule_type") == "protein"
            ]
        if supplied and sorted(supplied) != sorted(chains.values()):
            raise ToolFailed(
                "INPUT_SEQUENCE_MISMATCH",
                "Native input sequences differ from the reviewed construct.",
            )
    if tool == "infer_proteinmpnn_native":
        pdb = arguments.get("input_pdb")
        if not isinstance(pdb, str):
            raise ToolUnavailable(
                "BACKBONE_LOCAL_AUDIT_REQUIRED",
                "Bind a verified backbone structure for local input auditing.",
            )
        info, _, atom_rows = read_structure(pdb)
        designed = arguments.get("input_pdb_chains")
        if not designed or len(designed) != 1 or designed[0] not in info["chains"]:
            raise ToolUnavailable(
                "DESIGN_CHAIN_REQUIRED",
                "Select exactly one existing binder chain; do not redesign the target.",
            )
        residues = {row[1] for row in atom_rows if row[0] == designed[0]}
        for residue in residues:
            names = {row[2] for row in atom_rows if row[0] == designed[0] and row[1] == residue}
            if not {"N", "CA", "C", "O"}.issubset(names):
                raise ToolUnavailable(
                    "BACKBONE_ATOMS_REQUIRED",
                    "ProteinMPNN needs complete N/CA/C/O atoms for every design residue.",
                )
        if len(info["chains"][designed[0]]) != acceptance.get("binder_length"):
            raise ToolFailed(
                "BINDER_LENGTH_MISMATCH", "Reviewed length differs from actual backbone."
            )
        if designed[0] in acceptance.get("fixed_target_chains", []):
            raise ToolFailed(
                "TARGET_REDESIGN_FORBIDDEN", "A fixed target chain cannot be redesigned."
            )
    if step.agent == "A5a":
        protein = arguments.get("protein")
        if not isinstance(protein, str):
            raise ToolUnavailable(
                "RECEPTOR_LOCAL_AUDIT_REQUIRED",
                "Bind the reviewed receptor bytes for a local audit.",
            )
        read_structure(protein)
        expected_hash = acceptance.get("receptor_sha256")
        if expected_hash and hashlib.sha256(protein.encode()).hexdigest() != expected_hash:
            raise ToolFailed(
                "RECEPTOR_HASH_MISMATCH", "Docking receptor differs from reviewed bytes."
            )
        path = docking_reference(workflow, acceptance)
        if path:
            if hashlib.sha256(path.read_bytes()).hexdigest() != acceptance.get("reference_sha256"):
                raise ToolFailed("REFERENCE_HASH_MISMATCH", "Reviewed reference ligand changed.")
            from rdkit import Chem

            ref = next((m for m in Chem.SDMolSupplier(str(path), removeHs=True) if m), None)
            mol = Chem.MolFromSmiles(arguments.get("ligand", ""))
            if ref is None or mol is None or Chem.MolToInchiKey(ref) != Chem.MolToInchiKey(mol):
                raise ToolFailed(
                    "REFERENCE_CHEMISTRY_MISMATCH",
                    "Redocking reference differs from submitted ligand.",
                )
        else:
            passed = any(
                r.get("validation", {}).get("reference_redocking_qc") == "PASS"
                for r in workflow.output["steps"].values()
            )
            if not passed or not acceptance.get("pocket_center"):
                raise ToolUnavailable(
                    "REDOCKING_CONTROL_REQUIRED",
                    (
                        "A passed reference control and reviewed pocket are required befor"
                        "e candidate docking."
                    ),
                )
    if step.agent == "A6":
        if not step.md_review:
            raise ToolUnavailable(
                "MD_SYSTEM_REVIEW_REQUIRED", "Supply a reviewed system for this branch."
            )
        path = workflow.t.structural.store.resolve_input(step.md_review.manifest.path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != step.md_review.manifest_sha256:
            raise ToolFailed(
                "MD_MANIFEST_HASH_MISMATCH", "Reviewed native system manifest changed."
            )
        manifest = json.loads(path.read_text())
        if manifest.get("branch") != step.branch:
            raise ToolFailed(
                "MD_BRANCH_MISMATCH", "The MD system belongs to a different scientific branch."
            )
        expected_agent = "A5a" if step.branch == "small_molecule" else "A5b"
        hashes = [
            workflow.records[s.id]["sha256"]
            for s in workflow.t.request.steps
            if s.agent == expected_agent and s.id in workflow.records
        ]
        if manifest.get("source_artifact_sha256") not in hashes:
            raise ToolUnavailable(
                "MD_POSE_PROVENANCE_REQUIRED",
                (
                    "Native MD construction must cite a verified pose/complex artifact"
                    " from this branch."
                ),
            )
    # Batch manifests are real uploaded inputs, not fabricated names/paths. The remote
    # runner validates the complete live schema; local hashes bind reviewed artifacts.
    if tool.startswith("submit_") and step.agent != "A6":
        manifest = arguments.get("input_manifest")
        if not isinstance(manifest, dict) or manifest.get("sha256") != acceptance.get(
            "input_manifest_sha256"
        ):
            raise ToolUnavailable(
                "BATCH_INPUT_REVIEW_REQUIRED",
                "A reviewed immutable batch input manifest is required.",
            )


def docking_reference(workflow, acceptance):
    if acceptance.get("reference_preparation_id"):
        from .service import IntegrationService

        t = workflow.t
        source = IntegrationService(t.settings, t.literature, t.qsar, t.structural, t.nebius)
        return source.artifact(acceptance["reference_preparation_id"], "reference_55C.sdf")
    if acceptance.get("reference_sdf"):
        return workflow.t.structural.store.resolve_input(acceptance["reference_sdf"])
    return None
