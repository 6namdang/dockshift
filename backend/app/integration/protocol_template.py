"""Build an executable, zero-budget protocol from sealed real preparation files.

The protocol explicitly contains missing design/MD inputs. It is executable as
preflight, not a claim that the final experiment is scientifically ready.
"""

import argparse
import hashlib
import json
from pathlib import Path

from app.config import Settings

from .models import RunRequest
from .service import IntegrationService


def template(service, preparation_id):
    report = service.report(preparation_id)
    plan = report["outputs"]["docking_preparation"]
    # Use the deposited SEQRES construct, not concatenated observed fragments.
    sequence = None
    for path in service.directory(preparation_id).glob("polymer_*.json"):
        data = json.loads(path.read_text())
        if "O14746" in data.get("rcsb_polymer_entity_container_identifiers", {}).get(
            "uniprot_ids", []
        ):
            sequence = (
                data["entity_poly"]["pdbx_seq_one_letter_code_can"]
                .replace("\n", "")
                .replace(" ", "")
            )
    if not sequence:
        raise ValueError("Sealed preparation lacks the complete deposited target sequence")

    def binding(step, pointer, argument):
        return {"step": step, "pointer": pointer, "argument": argument}

    steps = [
        {
            "id": "experimental-target",
            "agent": "A2",
            "branch": "shared",
            "job": {
                "tool": "use_prepared_structure",
                "arguments": {"preparation_id": preparation_id},
            },
            "acceptance": {
                "unresolved_regions_review": None,
                "blocked_prerequisites": [
                    (
                        "Review 181 unobserved residues, excluded components, protonation "
                        "and intended docking construct."
                    )
                ],
            },
        },
        {
            "id": "generate-molecules",
            "agent": "A3",
            "branch": "small_molecule",
            "job": {
                "tool": "genmol_generate",
                "arguments": {
                    "smiles": "[*{20-30}]",
                    "num_molecules": 1,
                    "scoring": "QED",
                    "unique": True,
                },
            },
            "acceptance": {
                "max_heavy_atoms": 80,
                "blocked_prerequisites": [
                    (
                        "Named scientific reviewer; unconstrained generation is not target"
                        "-specific design."
                    )
                ],
            },
        },
        {
            "id": "design-backbone",
            "agent": "A4",
            "branch": "biologic",
            "job": {"tool": "submit_rfdiffusion", "arguments": {}},
            "acceptance": {
                "fixed_chains": {},
                "chain_lengths": {},
                "blocked_prerequisites": [
                    (
                        "Reviewed exposed epitope, exact target construct, fixed residues,"
                        " contigs, scaffold length, uploaded native input manifest and pro"
                        "vider qualification."
                    )
                ],
            },
        },
        {
            "id": "design-sequence",
            "agent": "A4",
            "branch": "biologic",
            "job": {
                "tool": "infer_proteinmpnn_native",
                "arguments": {
                    "input_pdb": "",
                    "input_pdb_chains": ["B"],
                    "num_seq_per_target": 1,
                    "random_seed": 2026,
                    "sampling_temp": [0.1],
                },
            },
            "bindings": [binding("design-backbone", "/data/structures/0/structure", "/input_pdb")],
            "acceptance": {
                "binder_length": None,
                "fixed_target_chains": ["A"],
                "blocked_prerequisites": [
                    (
                        "Actual target/binder chain mapping and backbone length from revie"
                        "wed generated scaffold."
                    )
                ],
            },
        },
        {
            "id": "redocking-control",
            "agent": "A5a",
            "branch": "small_molecule",
            "job": {
                "tool": "infer_diffdock_native",
                "arguments": {
                    "protein": "",
                    "ligand": plan["ligand_smiles"],
                    "num_poses": 4,
                    "random_seed": 2026,
                },
            },
            "bindings": [
                binding("experimental-target", "/data/structures/0/structure", "/protein")
            ],
            "acceptance": {
                "control": True,
                "receptor_sha256": plan["receptor_sha256"],
                "reference_preparation_id": preparation_id,
                "reference_sha256": plan["reference_sdf_sha256"],
                "blocked_prerequisites": [
                    (
                        "Reviewed reference microstate and receptor; same-frame RMSD must "
                        "pass 2 angstrom."
                    )
                ],
            },
        },
        {
            "id": "candidate-docking",
            "agent": "A5a",
            "branch": "small_molecule",
            "job": {
                "tool": "infer_diffdock_native",
                "arguments": {"protein": "", "ligand": "", "num_poses": 4, "random_seed": 2026},
            },
            "bindings": [
                binding("experimental-target", "/data/structures/0/structure", "/protein"),
                binding("generate-molecules", "/data/molecules/0/smiles", "/ligand"),
            ],
            "acceptance": {
                "receptor_sha256": plan["receptor_sha256"],
                "pocket_center": report["outputs"]["structure_input_audit"][
                    "ligand_centroid_angstrom"
                ],
                "blocked_prerequisites": [
                    (
                        "Passed redocking control; native pose chemistry and reviewed-site"
                        " geometry checks."
                    )
                ],
            },
        },
        {
            "id": "predict-complex",
            "agent": "A5b",
            "branch": "biologic",
            "job": {
                "tool": "boltz2_predict_native",
                "arguments": {
                    "polymers": [
                        {"id": "A", "molecule_type": "protein", "sequence": ""},
                        {"id": "B", "molecule_type": "protein", "sequence": ""},
                    ]
                },
            },
            "bindings": [
                binding("target", "/data/sequence", "/polymers/0/sequence"),
                binding("design-sequence", "/data/sequences/0/sequence", "/polymers/1/sequence"),
            ],
            "acceptance": {
                "chains": {"A": sequence, "B": ""},
                "interface_chains": ["A", "B"],
                "minimum_iptm": 0.6,
                "minimum_plddt": 70,
                "blocked_prerequisites": [
                    (
                        "Review canonical-versus-deposited sequence and insert actual desi"
                        "gned binder sequence in acceptance.chains.B; thresholds are propo"
                        "sed, not validated."
                    )
                ],
            },
        },
    ]
    for branch in ("small_molecule", "biologic"):
        steps.append(
            {
                "id": "md-" + branch.replace("_", "-"),
                "agent": "A6",
                "branch": branch,
                "job": {"tool": "submit_openmm_workflow", "arguments": {}},
                "acceptance": {
                    "blocked_prerequisites": [
                        (
                            "Reviewed repaired/protonated assembly, native ligand parameters w"
                            "here applicable, force fields, solvated topology/coordinates, pre"
                            "processing, real upload manifest, branch pose SHA, exact native o"
                            "utputs and convergence analysis."
                        )
                    ]
                },
            }
        )
    request = RunRequest(
        workflow="collective",
        branches=["small_molecule", "biologic"],
        literature_query="hTERT BIBR1532 telomerase inhibition biologic delivery",
        target={
            "label": "hTERT",
            "accession": "O14746",
            "structure_id": "9Q14",
            "structure_kind": "experimental",
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
        },
        budget={"max_submissions": 0, "max_llm_calls": 0},
        use_nebius_llm=False,
        steps=steps,
    )
    return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preparation_id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    service = IntegrationService(Settings(), None, None, None, None)
    request = template(service, args.preparation_id)
    with args.output.open("x") as handle:
        handle.write(request.model_dump_json(indent=2))
    print(
        json.dumps(
            {
                "status": "BLOCKED_REVIEW_REQUIRED",
                "protocol": str(args.output),
                "max_submissions": 0,
                "scientific_jobs_submitted": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
