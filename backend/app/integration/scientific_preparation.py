"""No-compute preparation of deposited hTERT/55C inputs and MD prerequisites."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from importlib.metadata import version

import numpy as np
from jsonschema import Draft202012Validator
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign

from .md_protocols import create_md_drafts
from .scienceclaw.adapters.base import ToolUnavailable

TOOLS = {
    "infer_diffdock_native": "diffdock",
    "submit_gromacs_workflow": "gromacs",
    "submit_amber_workflow": "amber",
    "submit_openmm_workflow": "openmm",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pdb_xyz(line):
    xyz = np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])])
    if not np.isfinite(xyz).all():
        raise ValueError("PDB has non-finite coordinates")
    return xyz


def structure_inputs(pdb: str, ccd: dict, chain: str):
    """Extract coordinates, preserving the deposited frame; do not invent missing atoms."""
    if len([line for line in pdb.splitlines() if line.startswith("MODEL ")]) > 1:
        raise ValueError("Select one experimental model explicitly")
    template = Chem.MolFromSmiles(ccd["rcsb_chem_comp_descriptor"]["SMILES_stereo"])
    if template is None or ccd["chem_comp"]["id"] != "55C":
        raise ValueError("55C chemical definition is invalid")
    atoms = [line.ljust(80) for line in pdb.splitlines() if line.startswith(("ATOM  ", "HETATM"))]
    ligand = [line for line in atoms if line[:6].strip() == "HETATM" and line[17:20] == "55C"]
    groups = {(line[21], line[22:27]) for line in ligand}
    if len(groups) != 1 or next(iter(groups))[0] != chain:
        raise ValueError("Expected one 55C bound to the verified TERT chain")
    receptor = [line for line in atoms if line.startswith("ATOM  ") and line[21] == chain]
    if not receptor or any(line[16] not in {" ", "A"} for line in receptor + ligand):
        raise ValueError("Receptor missing or alternate conformers need explicit review")
    if any(float(line[54:60]) <= 0 for line in receptor + ligand):
        raise ValueError("Zero-occupancy input atoms require review")
    ligand_pdb = "\n".join(ligand) + "\nEND\n"
    bound = Chem.MolFromPDBBlock(ligand_pdb, sanitize=False, removeHs=True)
    if bound is None or bound.GetNumHeavyAtoms() != template.GetNumHeavyAtoms():
        raise ValueError("Experimental ligand is incomplete")
    bound = AllChem.AssignBondOrdersFromTemplate(template, bound)
    Chem.SanitizeMol(bound)
    Chem.AssignStereochemistryFrom3D(bound)
    if Chem.MolToInchiKey(bound) != Chem.MolToInchiKey(template):
        raise ValueError("Deposited ligand chemistry/stereochemistry does not match CCD")
    protein_xyz = np.array([pdb_xyz(line) for line in receptor])
    ligand_xyz = np.array([pdb_xyz(line) for line in ligand])
    distances = np.linalg.norm(protein_xyz[:, None, :] - ligand_xyz[None, :, :], axis=2).min(axis=1)
    residues = sorted({int(line[22:26]) for line in receptor})
    gaps = [[a + 1, b - 1] for a, b in zip(residues, residues[1:], strict=False) if b > a + 1]
    near = sorted(
        {
            f"{line[21]}:{line[17:20].strip()}:{line[22:27].strip()}"
            for line, distance in zip(receptor, distances, strict=True)
            if distance <= 5
        }
    )
    excluded = [line for line in atoms if line[21] != chain and line.startswith("ATOM  ")]
    excluded_near = []
    for line in excluded:
        if np.linalg.norm(ligand_xyz - pdb_xyz(line), axis=1).min() <= 5:
            excluded_near.append(f"{line[21]}:{line[17:20].strip()}:{line[22:27].strip()}")
    report = {
        "protein_chain": chain,
        "protein_atoms": len(receptor),
        "observed_residues": len(residues),
        "observed_number_range": [min(residues), max(residues)],
        "internal_residue_number_gaps": gaps,
        "ligand_heavy_atoms": bound.GetNumHeavyAtoms(),
        "ligand_inchikey": Chem.MolToInchiKey(template),
        "canonical_smiles": Chem.MolToSmiles(template),
        "ccd_formal_charge": Chem.GetFormalCharge(template),
        "ligand_centroid_angstrom": ligand_xyz.mean(axis=0).tolist(),
        "contact_residues_within_5_angstrom": near,
        "excluded_polymer_contacts_within_5_angstrom": sorted(set(excluded_near)),
        "excluded_atom_records_by_chain": dict(Counter(line[21] for line in excluded)),
        "limitations": [
            "Full deposited TERT chain used; no spatial cropping or fabricated residues.",
            "RNA, DNA, accessory proteins, waters and heterogens excluded from this "
            "protein-only DiffDock input; biological environment requires review.",
            "Deposited neutral CCD microstate is not an MD protonation determination.",
            "Missing residues, alternate states and termini require scientist review.",
        ],
    }
    return "\n".join(receptor) + "\nEND\n", ligand_pdb, bound, report


class ScientificPreparation:
    def __init__(self, tools):
        self.t = tools
        self.out = tools.out
        self.state = {}

    def save(self, name, data):
        with (self.out / name).open("x") as f:
            json.dump(self.t.redact(data), f, indent=2, allow_nan=False)

    async def fetch(self, name, url):
        response = await self.t.qsar.client.get(url)
        response.raise_for_status()
        with (self.out / name).open("xb") as f:
            f.write(response.content)
        return response

    async def dispatch(self, agent):
        if agent == "A1":
            entry = await self.fetch(
                "rcsb_entry.json", "https://data.rcsb.org/rest/v1/core/entry/9Q14"
            )
            ccd = await self.fetch(
                "rcsb_55C.json", "https://data.rcsb.org/rest/v1/core/chemcomp/55C"
            )
            structure = await self.fetch(
                "source_9Q14.pdb", "https://files.rcsb.org/download/9Q14.pdb"
            )
            identities = []
            identifiers = entry.json()["rcsb_entry_container_identifiers"]
            for entity in identifiers["polymer_entity_ids"]:
                response = await self.fetch(
                    f"polymer_{entity}.json",
                    f"https://data.rcsb.org/rest/v1/core/polymer_entity/9Q14/{entity}",
                )
                row = response.json()
                container = row.get("rcsb_polymer_entity_container_identifiers", {})
                if "O14746" in (container.get("uniprot_ids") or []):
                    identities.append(row)
            if len(identities) != 1:
                raise ValueError("RCSB does not uniquely map the human TERT accession")
            chains = identities[0]["entity_poly"]["pdbx_strand_id"].split(",")
            if len(chains) != 1:
                raise ValueError("Choose one mapped TERT chain explicitly")
            self.state.update(pdb=structure.text, ccd=ccd.json(), chain=chains[0].strip())
            result = {
                "pdb_id": "9Q14",
                "target_accession": "O14746",
                "chain": self.state["chain"],
                "title": entry.json()["struct"]["title"],
                "ccd": "55C",
                "source_hashes": {
                    name: digest((self.out / name).read_bytes())
                    for name in ("source_9Q14.pdb", "rcsb_entry.json", "rcsb_55C.json")
                },
                "verification": "Live RCSB polymer-entity accession mapping and CCD definition",
            }
            self.t.verified_outputs["structural_sources"] = result
            return result, "Verified primary RCSB 9Q14/55C records and hTERT chain mapping."
        if agent == "A2":
            receptor, ligand, molecule, audit = structure_inputs(
                self.state["pdb"], self.state["ccd"], self.state["chain"]
            )
            (self.out / "receptor_htert.pdb").write_text(receptor)
            (self.out / "reference_55C.pdb").write_text(ligand)
            writer = Chem.SDWriter(str(self.out / "reference_55C.sdf"))
            writer.write(molecule)
            writer.close()
            self.state.update(audit=audit, receptor=receptor, bound=molecule)
            self.save("structure_input_audit.json", audit)
            self.t.verified_outputs["structure_input_audit"] = audit
            return (
                audit,
                "Deposited protein-only receptor and chemically checked bound reference extracted.",
            )
        if agent == "A3":
            from .scienceclaw.adapters.chemistry import RDKitAdapter

            audit = RDKitAdapter().audit(self.state["audit"]["canonical_smiles"])
            if not audit.valid:
                raise ValueError("CCD BIBR1532 failed chemical admissibility")
            self.state["smiles"] = audit.canonical_smiles
            result = {
                "canonical_smiles": audit.canonical_smiles,
                "inchikey": audit.inchikey,
                "rdkit_version": version("rdkit"),
                "scope": "Deposited ligand identity; no molecule generation or parameterization.",
            }
            self.save("ligand_identity.json", result)
            return (
                result,
                "BIBR1532 chemical identity, valence and stereochemistry checked locally.",
            )
        if agent == "A5a":
            schemas, readiness = {}, {}
            discovered = {t.name: t for t in await self.t.nebius.client.list_tools()}
            for tool, model in TOOLS.items():
                if tool not in discovered:
                    raise ToolUnavailable(
                        "SCIENTIFIC_TOOL_MISSING", f"Nebius does not advertise {tool}."
                    )
                schemas[tool] = discovered[tool].input_schema
                self.save(f"schema_{tool}.json", schemas[tool])
                from app.nebius.service import _unwrap

                metadata = _unwrap(
                    await self.t.nebius.client.call(
                        "get_model_schema", {"model_id": model, "summary_only": True}
                    )
                )
                self.save(f"metadata_{model}.json", metadata)
                readiness[model] = metadata.get("qualification") or metadata.get("readiness")
            args = {
                "protein": self.state["receptor"],
                "ligand": self.state["smiles"],
                "num_poses": 4,
                "random_seed": 2026,
                "wait_seconds": 0,
                "idempotency_key": f"{self.t.run_id}-A5a-diffdock",
            }
            Draft202012Validator(schemas["infer_diffdock_native"]).validate(args)
            self.save("diffdock_arguments.json", args)
            plan = {
                "preparation_id": self.t.run_id,
                "status": "PREPARED_REVIEW_REQUIRED",
                "schema_valid": True,
                "remote_job_submitted": False,
                "receptor_sha256": digest(self.state["receptor"].encode()),
                "reference_sdf_sha256": digest((self.out / "reference_55C.sdf").read_bytes()),
                "arguments_sha256": digest((self.out / "diffdock_arguments.json").read_bytes()),
                "ligand_smiles": self.state["smiles"],
                "redocking_rmsd_threshold_angstrom": 2.0,
                "review_required": [
                    "Receptor gaps/termini and excluded nucleic-acid contacts",
                    "Ligand protonation and selected experimental model",
                ],
                "provider_qualification": readiness,
                "source": self.t.verified_outputs["structural_sources"],
            }
            self.state["schemas"] = schemas
            self.save("docking_plan.json", plan)
            self.t.verified_outputs["docking_preparation"] = plan
            return (
                plan,
                "DiffDock request schema validated; no docking job submitted or score produced.",
            )
        if agent == "A6":
            if "schemas" not in self.state:
                raise ToolUnavailable(
                    "SCHEMAS_REQUIRED", "A5a preparation must discover scientific schemas."
                )
            md = create_md_drafts(self.out, self.state["schemas"])
            self.save("md_prerequisites.json", md)
            self.t.verified_outputs["md_preparation"] = md
            return (
                {"_status": "BLOCKED", "_error_code": "MD_SYSTEM_NOT_PARAMETERIZED", **md},
                "MD protocol drafts validate against Nebius schemas; "
                "physical system/topology is unprepared.",
            )
        if agent in {"A4", "A5b"}:
            raise ToolUnavailable(
                "BINDER_NOT_REQUESTED", "This preparation is the small-molecule branch only."
            )
        return await self.t.dispatch_advanced(agent)


def validate_diffdock(
    result, smiles, reference_path=None, threshold=2.0, receptor=None, pocket_center=None
):
    """Validate real SDF pose chemistry, coordinates and same-frame redocking RMSD."""
    template = Chem.MolFromSmiles(smiles)
    reference = (
        next((m for m in Chem.SDMolSupplier(str(reference_path), removeHs=True) if m), None)
        if reference_path
        else None
    )
    if (reference_path and reference is None) or template is None:
        raise ValueError("Valid ligand/reference structures required")
    identity = Chem.MolToInchiKey(template)
    if reference is not None and Chem.MolToInchiKey(reference) != identity:
        raise ValueError("Reference ligand identity mismatch")
    documents = [
        a["data"]
        for a in result.get("artifacts", [])
        if a.get("hash_verified") and isinstance(a.get("data"), dict)
    ]
    rows = []
    for document in documents:
        poses, scores = document.get("ligand_positions"), document.get("position_confidence")
        if not isinstance(poses, list) or not isinstance(scores, list) or len(poses) != len(scores):
            continue
        for i, (text, score) in enumerate(zip(poses, scores, strict=True)):
            if (
                not isinstance(text, str)
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
            ):
                raise ValueError("Pose SDF and numeric native confidence required")
            if not np.isfinite(score):
                raise ValueError("Non-finite DiffDock confidence")
            mol = Chem.MolFromMolBlock(text.split("$$$$")[0], removeHs=True)
            if mol is None or not mol.GetNumConformers() or not mol.GetConformer().Is3D():
                raise ValueError("Pose is not a valid 3D SDF structure")
            Chem.AssignStereochemistryFrom3D(mol)
            if (
                Chem.MolToInchiKey(mol) != identity
                or not np.isfinite(mol.GetConformer().GetPositions()).all()
            ):
                raise ValueError("Docked pose does not match ligand chemistry/stereochemistry")
            row = {"rank": i + 1, "diffdock_pose_confidence": float(score)}
            if reference is not None:
                row["same_frame_symmetry_corrected_rmsd_angstrom"] = float(
                    rdMolAlign.CalcRMS(mol, reference)
                )
            else:
                from .scientific_outputs import read_structure

                if receptor is None or pocket_center is None:
                    raise ToolUnavailable(
                        "RECEPTOR_FRAME_REQUIRED",
                        "Reviewed receptor and pocket center are required.",
                    )
                _, xyz, _ = read_structure(receptor)
                positions = mol.GetConformer().GetPositions()
                nearest = float(np.linalg.norm(positions[:, None] - xyz[None, :], axis=-1).min())
                center = np.asarray(pocket_center, dtype=float)
                if center.shape != (3,) or not np.isfinite(center).all():
                    raise ValueError("Finite reviewed pocket center required")
                center_distance = float(np.linalg.norm(positions.mean(axis=0) - center))
                if nearest < 0.8 or nearest > 6 or center_distance > 8:
                    raise ValueError("Docked pose clashes or lies outside the reviewed site")
                row.update(
                    receptor_contact_distance_angstrom=nearest,
                    pocket_centroid_distance_angstrom=center_distance,
                )
            rows.append(row)
    if not rows:
        raise ToolUnavailable(
            "DIFFDOCK_FORMAT_UNVERIFIED", "No verified native 3D pose/confidence pairs."
        )
    return {
        "execution_status": "SUCCEEDED",
        "poses": rows,
        "affinity_computed": False,
        "reference_redocking_qc": "PASS"
        if reference is not None
        and rows[0]["same_frame_symmetry_corrected_rmsd_angstrom"] <= threshold
        else "FAIL"
        if reference is not None
        else "NOT_APPLICABLE",
        "threshold_angstrom": threshold,
        "limitations": [
            "Confidence is model-native pose ranking, not binding affinity.",
            "Redocking QC does not establish inhibition or clinical efficacy.",
        ],
    }
