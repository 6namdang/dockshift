"""Opt-in LOCAL AMBER-family construction, never a remote compute submission.

A reviewed microstate/assembly is mandatory. Large unresolved loops are not
invented by this adapter. Optional native tools do real work when installed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
from pathlib import Path

from pydantic import Field
from rdkit import Chem

from .models import StrictModel
from .scienceclaw.adapters.base import ToolFailed, ToolUnavailable
from .scientific_outputs import read_structure


class BuildRecipe(StrictModel):
    schema_version: str = "dockshift-system-recipe/v1"
    branch: str = Field(pattern=r"^(small_molecule|biologic)$")
    macromolecule_pdb: str
    macromolecule_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_chains: dict[str, str]
    ligand_sdf: str | None = None
    ligand_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    ligand_smiles: str | None = None
    ligand_net_charge: int | None = Field(None, ge=-5, le=5)
    ph: float = Field(ge=0, le=14)
    ionic_strength_molar: float = Field(0.15, ge=0, le=1)
    solvent_padding_angstrom: float = Field(12, ge=10, le=25)
    # Explicit histidine variants, indexed in native topology residue order.
    protonation_variants: list[str | None]
    assembly_reviewed_by: str = Field(min_length=1, max_length=200)
    protocol_reviewed_by: str = Field(min_length=1, max_length=200)
    unresolved_regions_resolution: str = Field(min_length=10, max_length=2000)
    # Tiny modeled loops are allowed only with exact residue identities reviewed.
    approved_short_loops: dict[str, list[str]] = Field(default_factory=dict)
    random_seed: int = Field(2026, ge=1, le=2147483647)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def requirements(recipe):
    tools = (
        ("tleap", "antechamber", "parmchk2") if recipe.branch == "small_molecule" else ("tleap",)
    )
    modules = ("pdbfixer", "openmm")
    missing = [name for name in tools if not shutil.which(name)]
    missing += [name for name in modules if importlib.util.find_spec(name) is None]
    return {
        "status": "BLOCKED" if missing else "PREPARED_REVIEW_REQUIRED",
        "missing": missing,
        "computation_performed": False,
        "remote_submission_performed": False,
        "force_fields": {
            "protein": "ff14SB",
            "RNA": "OL3",
            "DNA": "OL15",
            "water": "TIP3P",
            "ligand": "GAFF2/AM1-BCC" if recipe.branch == "small_molecule" else "not applicable",
        },
        "scientific_review": "Required; dependencies alone do not qualify the prepared system.",
    }


def native(argv, out):
    # Fixed native executables/argv only. No shell, model-authored commands or inherited secrets.
    import os

    env = {
        k: v
        for k, v in os.environ.items()
        if k in ("PATH", "AMBERHOME", "CONDA_PREFIX", "TMPDIR", "LANG")
    }
    result = subprocess.run(
        argv, cwd=out, env=env, capture_output=True, text=True, timeout=600, check=False
    )
    with (out / f"command_{len(list(out.glob('command_*.json')))}.json").open("x") as handle:
        json.dump(
            {
                "argv": argv,
                "executable_sha256": digest(Path(shutil.which(argv[0])).resolve()),
                "exit_code": result.returncode,
                "stdout": result.stdout[-20000:],
                "stderr": result.stderr[-20000:],
            },
            handle,
            indent=2,
        )
    if result.returncode:
        raise ToolFailed(
            "NATIVE_PREPARATION_FAILED",
            "Native parameterization failed; inspect the local receipt.",
        )
    return result.stdout


def restore_ligand_pose(mol2_path, pose):
    """Keep real native charges/types while restoring reviewed coordinates by graph map."""
    typed = Chem.MolFromMol2File(str(mol2_path), removeHs=False)
    if typed is None or Chem.MolToInchiKey(Chem.RemoveHs(typed)) != Chem.MolToInchiKey(
        Chem.RemoveHs(pose)
    ):
        raise ValueError("Parameterized ligand identity/stereochemistry changed")
    mapping = typed.GetSubstructMatch(pose, useChirality=True)
    if len(mapping) != pose.GetNumAtoms() or typed.GetNumAtoms() != pose.GetNumAtoms():
        raise ValueError("Cannot map every parameterized ligand atom to the reviewed pose")
    xyz = {
        native: pose.GetConformer().GetAtomPosition(original)
        for original, native in enumerate(mapping)
    }
    lines = mol2_path.read_text().splitlines()
    active = False
    index = 0
    for i, line in enumerate(lines):
        if line.startswith("@<TRIPOS>"):
            active = line == "@<TRIPOS>ATOM"
            continue
        if active and line.strip():
            fields = line.split()
            position = xyz[index]
            fields[2:5] = [f"{v:.6f}" for v in position]
            lines[i] = " ".join(fields)
            index += 1
    if index != pose.GetNumAtoms():
        raise ValueError("Native MOL2 atom section differs from the molecular graph")
    mol2_path.write_text("\n".join(lines) + "\n")


def build_system(recipe, input_store, out: Path, execute=False):
    """Construct real files only on explicit local execution; never enable remote gates."""
    if recipe.schema_version != "dockshift-system-recipe/v1":
        raise ValueError("Unknown system recipe version")
    source = input_store.resolve_input(recipe.macromolecule_pdb)
    if digest(source) != recipe.macromolecule_sha256:
        raise ValueError("Reviewed assembly changed")
    info, _, _ = read_structure(source.read_text())
    if info["chains"] != recipe.expected_chains:
        raise ValueError("Reviewed assembly chain sequence/coverage mismatch")
    if recipe.branch == "small_molecule":
        if any(
            v is None
            for v in (
                recipe.ligand_sdf,
                recipe.ligand_sha256,
                recipe.ligand_smiles,
                recipe.ligand_net_charge,
            )
        ):
            raise ToolUnavailable(
                "LIGAND_MICROSTATE_REQUIRED",
                "Reviewed ligand pose, microstate and charge required.",
            )
        ligand = input_store.resolve_input(recipe.ligand_sdf)
        if digest(ligand) != recipe.ligand_sha256:
            raise ValueError("Ligand pose changed")
        mol = Chem.SDMolSupplier(str(ligand), removeHs=False)[0]
        template = Chem.MolFromSmiles(recipe.ligand_smiles)
        if mol is None or template is None or not mol.GetConformer().Is3D():
            raise ValueError("A genuine 3D ligand and valid microstate are required")
        if (
            Chem.MolToInchiKey(Chem.RemoveHs(mol)) != Chem.MolToInchiKey(template)
            or Chem.GetFormalCharge(mol) != recipe.ligand_net_charge
        ):
            raise ValueError("Pose chemistry does not match reviewed protonation/charge")
    for line in source.read_text().splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and line[17:20].strip() in ("HOH", "WAT"):
            raise ToolUnavailable(
                "WATER_ASSEMBLY_REVIEW_REQUIRED",
                (
                    "Provide the reviewed unsolvated assembly; retained crystallograph"
                    "ic waters need an explicit separate recipe."
                ),
            )
    preflight = requirements(recipe)
    if not execute:
        return preflight
    if preflight["missing"]:
        raise ToolUnavailable(
            "LOCAL_PARAMETERIZERS_REQUIRED",
            "Missing local preparation dependencies: " + ", ".join(preflight["missing"]),
        )
    out.mkdir(parents=True, exist_ok=False)
    with (out / "recipe.json").open("x") as handle:
        json.dump(recipe.model_dump(mode="json"), handle, indent=2)
    # Imports are optional and never needed for ordinary Dockshift startup or QSAR.
    import openmm as mm
    from openmm import app, unit
    from pdbfixer import PDBFixer

    fixer = PDBFixer(filename=str(source))
    fixer.findMissingResidues()
    found = {f"{chain}:{offset}": names for (chain, offset), names in fixer.missingResidues.items()}
    if found != recipe.approved_short_loops or any(len(v) > 3 for v in found.values()):
        raise ToolUnavailable(
            "STRUCTURAL_REPAIR_REQUIRED",
            (
                "Unresolved regions need a reviewed structural model; only explici"
                "tly approved loops of at most three residues can be built locally"
                "."
            ),
        )
    fixer.findNonstandardResidues()
    if fixer.nonstandardResidues:
        raise ToolUnavailable(
            "NONSTANDARD_RESIDUES_REQUIRED",
            "Review modified residues/cofactors; no automatic substitution.",
        )
    # Ligand is supplied separately. Retain macromolecule only; no silent metal/cofactor removal.
    allowed = set(("HOH WAT A C G U DA DC DG DT").split())
    if any(
        r.name not in allowed
        and r.name not in __import__("app.integration.scientific_outputs", fromlist=["AA"]).AA
        for r in fixer.topology.residues()
    ):
        raise ToolUnavailable(
            "COFACTOR_PARAMETERS_REQUIRED", "Unknown assembly component needs explicit parameters."
        )
    fixer.findMissingAtoms()
    fixer.addMissingAtoms(seed=recipe.random_seed)
    forcefield = app.ForceField(
        "amber14/protein.ff14SB.xml",
        "amber14/RNA.OL3.xml",
        "amber14/DNA.OL15.xml",
        "amber14/tip3p.xml",
    )
    modeller = app.Modeller(fixer.topology, fixer.positions)
    if len(recipe.protonation_variants) != modeller.topology.getNumResidues():
        raise ValueError("Protonation variants must cover the exact repaired residue order")
    selected_variants = modeller.addHydrogens(
        forcefield, pH=recipe.ph, variants=recipe.protonation_variants
    )
    for residue, variant in zip(modeller.topology.residues(), selected_variants, strict=True):
        if variant in ("HID", "HIE", "HIP", "CYX", "ASH", "GLH", "LYN"):
            residue.name = variant
    with (out / "macromolecule.pdb").open("x") as handle:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, handle)
    assembly = "protein"
    if recipe.branch == "small_molecule":
        with Chem.SDWriter(str(out / "ligand.sdf")) as writer:
            writer.write(Chem.AddHs(mol, addCoords=True))
        native(
            [
                "antechamber",
                "-i",
                "ligand.sdf",
                "-fi",
                "sdf",
                "-o",
                "ligand.mol2",
                "-fo",
                "mol2",
                "-at",
                "gaff2",
                "-c",
                "bcc",
                "-nc",
                str(recipe.ligand_net_charge),
                "-rn",
                "LIG",
                "-s",
                "2",
            ],
            out,
        )
        native(
            ["parmchk2", "-i", "ligand.mol2", "-f", "mol2", "-o", "ligand.frcmod", "-s", "gaff2"],
            out,
        )
        restore_ligand_pose(out / "ligand.mol2", Chem.AddHs(mol, addCoords=True))
        # Keep reviewed coordinates and native charges/types, not an AM1 geometry replacement.
        assembly = "complex"
    leap = (
        "source leaprc.protein.ff14SB\nsource leaprc.RNA.OL3\nsource leaprc."
        "DNA.OL15\nsource leaprc.water.tip3p\n"
    )
    if recipe.branch == "small_molecule":
        leap += "source leaprc.gaff2\nloadamberparams ligand.frcmod\nlig = loadmol2 ligand.mol2\n"
    leap += "protein = loadpdb macromolecule.pdb\n"
    if assembly == "complex":
        leap += "complex = combine { protein lig }\n"
    leap += (
        f"check {assembly}\n"
        f"solvatebox {assembly} TIP3PBOX {recipe.solvent_padding_angstrom}\n"
        f"addionsrand {assembly} Na+ 0\naddionsrand {assembly} Cl- 0\n"
        f"saveamberparm {assembly} neutral.prmtop neutral.inpcrd\nquit\n"
    )
    (out / "neutral.leap").write_text(leap)
    native(["tleap", "-f", "neutral.leap"], out)
    neutral = app.AmberInpcrdFile(str(out / "neutral.inpcrd"))
    box = neutral.boxVectors
    if box is None:
        raise ValueError("Solvated system has no periodic box")
    # Explicit added salt pairs from actual periodic volume, beyond neutralizing ions.
    matrix = np_array_box(box, unit.nanometer)
    import numpy as np

    pairs = round(recipe.ionic_strength_molar * abs(float(np.linalg.det(matrix))) * 0.602214076)
    # Rebuild once with the exact same neutralization operations and explicit salt count.
    final = (
        leap[: leap.index(f"check {assembly}")]
        + leap[leap.index(f"check {assembly}") : leap.index("saveamberparm")]
    )
    if pairs:
        final += f"addionsrand {assembly} Na+ {pairs}\naddionsrand {assembly} Cl- {pairs}\n"
    final += (
        f"check {assembly}\nsaveamberparm {assembly} system.prmtop system.inpcrd\n"
        f"savepdb {assembly} system.pdb\nquit\n"
    )
    (out / "system.leap").write_text(final)
    native(["tleap", "-f", "system.leap"], out)
    coordinates = app.AmberInpcrdFile(str(out / "system.inpcrd"))
    topology = app.AmberPrmtopFile(
        str(out / "system.prmtop"), periodicBoxVectors=coordinates.boxVectors
    )
    system = topology.createSystem(
        nonbondedMethod=app.PME, nonbondedCutoff=1 * unit.nanometer, constraints=app.HBonds
    )
    if system.getNumParticles() != len(coordinates.positions):
        raise ValueError("Native topology/coordinate atom count mismatch")
    integrator = mm.VerletIntegrator(0.002 * unit.picoseconds)
    context = mm.Context(system, integrator, mm.Platform.getPlatformByName("Reference"))
    context.setPeriodicBoxVectors(*coordinates.boxVectors)
    context.setPositions(coordinates.positions)
    energy = (
        context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    )
    if not math.isfinite(energy):
        raise ValueError("Non-finite parameterized-system energy")
    nonbonded = next(f for f in system.getForces() if isinstance(f, mm.NonbondedForce))
    charge = sum(
        nonbonded.getParticleParameters(i)[0].value_in_unit(unit.elementary_charge)
        for i in range(system.getNumParticles())
    )
    if abs(charge) > 0.001:
        raise ValueError("Solvated system is not neutral")
    report = {
        "status": "NATIVE_PRECHECK_PASSED",
        "particle_count": system.getNumParticles(),
        "initial_potential_energy_kj_mol": energy,
        "system_charge_e": charge,
        "salt_pairs": pairs,
        "openmm_version": mm.__version__,
        "simulation_performed": False,
        "structure_repair": "REVIEW_REQUIRED",
        "convergence": "NOT_ASSESSED",
        "limitations": [
            (
                "Native topology loading/finite energy is not minimization, equili"
                "bration or physical validation."
            )
        ],
    }
    (out / "native_precheck.json").write_text(json.dumps(report, indent=2))
    manifest = {p.name: digest(p) for p in out.iterdir() if p.is_file()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return report


def np_array_box(box, length_unit):
    return [
        [
            component.value_in_unit(length_unit)
            if hasattr(component, "value_in_unit")
            else float(component)
            for component in vector
        ]
        for vector in box
    ]


def main():
    import argparse

    from app.config import Settings
    from app.structural import StructuralService

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument(
        "--execute-local",
        action="store_true",
        help="Explicit local parameterization only; never remote MD",
    )
    args = parser.parse_args()
    recipe = BuildRecipe.model_validate_json(args.recipe.read_text())
    store = StructuralService(Settings()).store
    import uuid

    out = store.root / ("prepared-system-" + uuid.uuid4().hex)
    try:
        report = build_system(recipe, store, out, execute=args.execute_local)
        print(json.dumps({"output": str(out) if out.exists() else None, **report}, indent=2))
    except (ToolUnavailable, ToolFailed) as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED" if isinstance(exc, ToolUnavailable) else "FAILED",
                    "code": exc.error_code,
                    "detail": exc.detail,
                    "remote_submission_performed": False,
                },
                indent=2,
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
