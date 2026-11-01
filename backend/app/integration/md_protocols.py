"""Native MD input drafts and fail-closed prerequisite/result checks.

These are proposed pilot protocols, not generated force-field parameters or
proof that the deposited system is simulation-ready. No engine is invoked here.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

from jsonschema import Draft202012Validator

from .scienceclaw.adapters.base import ToolUnavailable

STEPS = {"nvt": 10_000, "npt": 25_000, "md": 500_000}


def parameters_schema(tool_schema):
    definitions = tool_schema["$defs"]
    submit = definitions[tool_schema["properties"]["request"]["$ref"].rsplit("/", 1)[1]]
    return {"$defs": definitions, "$ref": submit["properties"]["parameters"]["$ref"]}


def create_md_drafts(out: Path, schemas: dict) -> dict:
    common = (
        "cutoff-scheme = Verlet\nnstlist = 20\ncoulombtype = PME\n"
        "rcoulomb = 1.0\nrvdw = 1.0\npbc = xyz\n"
    )
    em = "integrator = steep\nnsteps = 5000\nemtol = 1000\nemstep = 0.01\n" + common
    (out / "em.mdp").write_text("; DRAFT: reviewed solvated topology required\n" + em)
    for stage, steps in STEPS.items():
        text = (
            f"; DRAFT: {stage}; not executed\nintegrator = md\ndt = 0.002\nnsteps = {steps}\n"
            "constraints = h-bonds\nconstraint-algorithm = lincs\nlincs-order = 4\n"
            "tcoupl = V-rescale\ntc-grps = System\ntau-t = 1.0\nref-t = 300\n"
            "nstxout-compressed = 1000\nnstenergy = 1000\nDispCorr = EnerPres\n" + common
        )
        text += (
            "gen-vel = yes\ngen-temp = 300\ngen-seed = 2026\ncontinuation = no\npcoupl = no\n"
            if stage == "nvt"
            else "gen-vel = no\ncontinuation = yes\npcoupl = Parrinello-Rahman\n"
            "pcoupltype = isotropic\ntau-p = 2.0\nref-p = 1.0\ncompressibility = 4.5e-5\n"
        )
        (out / f"{stage}.mdp").write_text(text)
    gsteps, coordinate, checkpoint = [], "system.gro", None
    for stage in ("em", "nvt", "npt", "md"):
        args = [
            "-f",
            f"{stage}.mdp",
            "-c",
            coordinate,
            "-p",
            "topol.top",
            "-o",
            f"{stage}.tpr",
            "-maxwarn",
            "0",
        ]
        if checkpoint:
            args += ["-t", checkpoint]
        gsteps += [
            {
                "id": stage + "-compile",
                "command": "grompp",
                "args": args,
                "expected_outputs": [f"{stage}.tpr"],
            },
            {
                "id": stage + "-run",
                "command": "mdrun",
                "args": ["-s", f"{stage}.tpr", "-deffnm", stage],
                "expected_outputs": [f"{stage}.gro", f"{stage}.edr", f"{stage}.log"]
                + ([f"{stage}.xtc"] if stage != "em" else []),
            },
        ]
        coordinate = f"{stage}.gro"
        checkpoint = f"{stage}.cpt" if stage != "em" else None
    gromacs = {
        "schema": "fs2-serve.nebius.ai/gromacs-workflow-request/v1",
        "jobs": [{"id": "htert-pilot", "steps": gsteps}],
        "threads": 2,
        "max_wall_seconds": 3600,
    }
    amber_steps, coordinate = [], "system.inpcrd"
    for stage in ("em", "nvt", "npt", "md"):
        if stage == "em":
            control = "imin=1, maxcyc=5000, ncyc=2500, ntb=1, cut=10.0, ntpr=100,"
        else:
            control = (
                f"imin=0, nstlim={STEPS[stage]}, dt=0.002, ntc=2, ntf=2, cut=10.0, "
                "ntt=3, gamma_ln=1.0, temp0=300.0, ntpr=1000, ntwx=1000, "
                "ntwr=1000, ioutfm=1, "
            )
            control += (
                "irest=0, ntx=1, ntb=1, ntp=0, tempi=300.0, ig=2026,"
                if stage == "nvt"
                else "irest=1, ntx=5, ntb=2, ntp=1, pres0=1.0, taup=2.0, barostat=2,"
            )
        (out / f"{stage}.mdin").write_text(
            "DRAFT: reviewed system and parameters required\n&cntrl\n " + control + "\n/\n"
        )
        step = {
            "id": stage,
            "kind": "pmemd",
            "input": f"{stage}.mdin",
            "topology": "system.prmtop",
            "coordinates": coordinate,
            "output_prefix": stage,
            "task": "minimization" if stage == "em" else "dynamics",
        }
        if stage != "em":
            step["expected_nsteps"] = STEPS[stage]
        amber_steps.append(step)
        coordinate = stage + ".rst7"
    amber = {
        "schema": "fs2-serve.nebius.ai/amber-workflow-request/v1",
        "jobs": [{"id": "htert-pilot", "steps": amber_steps}],
        "backend": "cuda-spfp",
        "threads": 1,
        "max_wall_seconds": 3600,
    }
    openmm = {
        "schema": "fs2-serve.nebius.ai/openmm-workflow-request/v1",
        "jobs": [
            {
                "id": "htert-pilot",
                "system": {
                    "format": "amber",
                    "coordinates": "system.inpcrd",
                    "topology": "system.prmtop",
                },
                "steps": [
                    {"id": "em", "kind": "minimize", "max_iterations": 5000},
                    *[
                        {
                            "id": s,
                            "kind": "production" if s == "md" else "equilibrate",
                            "steps": n,
                            "timestep_ps": 0.002,
                            "temperature_k": 300,
                            "integrator": "langevin-middle",
                            "friction_per_ps": 1.0,
                            "pressure_bar": None if s == "nvt" else 1.0,
                            "reset_velocities": s == "nvt",
                            "report_interval": 1000,
                        }
                        for s, n in STEPS.items()
                    ],
                ],
            }
        ],
        "backend": "cuda",
        "precision": "mixed",
        "random_seed": 2026,
        "max_wall_seconds": 3600,
    }
    drafts = {"gromacs": gromacs, "amber": amber, "openmm": openmm}
    for engine, parameters in drafts.items():
        tool = f"submit_{engine}_workflow"
        Draft202012Validator(parameters_schema(schemas[tool])).validate(parameters)
        (out / f"{engine}_parameters.draft.json").write_text(json.dumps(parameters, indent=2))
    return {
        "status": "BLOCKED",
        "protocols_schema_valid": True,
        "protocols_reviewed": False,
        "simulation_executed": False,
        "production_duration_ps_proposed": 1000,
        "scope": "Proposed pilot only; equilibration/convergence not established",
        "force_field_proposal": {
            "protein": "AMBER ff14SB",
            "RNA": "OL3",
            "DNA": "OL15",
            "water": "TIP3P with matched ion parameters",
            "ligand": "GAFF2 + AM1-BCC",
            "selected_ligand_net_charge": None,
            "note": "Proposal only; no topology or ligand parameters generated.",
        },
        "missing": [
            "Reviewed biological assembly and repaired/capped missing residues",
            "Reviewed protonation/tautomer and ligand net charge at chosen pH",
            "Real ligand MOL2 partial charges and atom types plus FRCMOD parameters",
            "Complete solvated/ionized topology and coordinates with matched atom ordering",
            "Explicit RNA/DNA, accessory proteins, cofactors and metal treatment",
            "Validated restraints, ensemble, equilibration and production protocol",
            "Actual immutable Nebius input manifest; no upload IDs fabricated",
            "Scientist approval and expensive-compute authorization",
        ],
        "expected_bundle_files": {
            "gromacs": ["system.gro", "topol.top", "all topology includes"],
            "amber": ["system.prmtop", "system.inpcrd"],
            "openmm": ["system.prmtop", "system.inpcrd"],
        },
        "local_tools": {
            name: bool(shutil.which(name))
            for name in ("gmx", "tleap", "antechamber", "parmchk2", "acpype", "obabel")
        },
        "local_modules": {
            name: bool(importlib.util.find_spec(name))
            for name in ("openmm", "openmmforcefields", "pdbfixer", "parmed")
        },
    }


def validate_md_result(result: dict, requested_steps: dict[str, int]) -> dict:
    """Validate execution evidence, never infer trajectory quality from job success."""
    if not requested_steps or any(
        isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in requested_steps.values()
    ):
        raise ValueError("Explicit positive native dynamics step counts are required")
    artifacts = result.get("artifacts", [])
    if not artifacts or not all(a.get("hash_verified") for a in artifacts):
        raise ToolUnavailable("MD_ARTIFACTS_REQUIRED", "Verified MD artifacts are required.")
    documents = [a["data"] for a in artifacts if isinstance(a.get("data"), dict)]
    for document in documents:
        if document.get("status", "").lower() != "succeeded":
            continue
        if not (document.get("engine_version") or document.get("model_version")):
            raise ToolUnavailable("MD_VERSION_REQUIRED", "Native engine/model version is absent.")
        steps = {s.get("id"): s for job in document.get("jobs", []) for s in job.get("steps", [])}
        if not all(name in steps for name in requested_steps):
            continue
        for name, expected in requested_steps.items():
            step = steps[name]
            if (
                step.get("status", "").lower() != "succeeded"
                or step.get("completed_steps") != expected
            ):
                raise ToolUnavailable(
                    "MD_STEP_COUNT_UNVERIFIED", "Native MD step counts do not match."
                )
        trajectory = [
            a for a in artifacts if a["filename"].endswith((".xtc", ".trr", ".dcd", ".nc"))
        ]
        if not trajectory:
            raise ToolUnavailable(
                "MD_TRAJECTORY_REQUIRED", "No verified trajectory bytes were retained."
            )
        return {
            "execution_status": "SUCCEEDED",
            "engine_version": document.get("engine_version") or document.get("model_version"),
            "requested_step_counts_verified": True,
            "trajectory_integrity_verified": True,
            "trajectory_physical_quality": "NOT_ASSESSED",
            "convergence": "NOT_ASSESSED",
            "binding_stability": "NOT_ASSESSED",
            "experimental_efficacy": "NOT_ESTABLISHED",
        }
    raise ToolUnavailable(
        "MD_NATIVE_RESULT_UNSUPPORTED",
        "Native MD stage metadata needs an engine-specific validated parser.",
    )
