"""Seal actual locally constructed MD inputs. Never upload or execute a model."""

import hashlib
import json
import shutil
import tarfile
from pathlib import Path

from .md_protocols import create_md_drafts
from .scienceclaw.adapters.base import ToolUnavailable


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal_system(source: Path, out: Path, schemas, engine, reviewer, source_artifact_sha256):
    if (
        engine not in ("gromacs", "amber", "openmm")
        or not reviewer
        or len(source_artifact_sha256) != 64
    ):
        raise ValueError("Native engine, scientist and source pose digest required")
    manifest = json.loads((source / "manifest.json").read_text())
    for name, digest in manifest.items():
        if Path(name).name != name or sha(source / name) != digest:
            raise ValueError("Prepared-system provenance changed")
    native = json.loads((source / "native_precheck.json").read_text())
    recipe = json.loads((source / "recipe.json").read_text())
    if native.get("status") != "NATIVE_PRECHECK_PASSED":
        raise ToolUnavailable(
            "NATIVE_PRECHECK_REQUIRED", "Native system construction did not pass preprocessing."
        )
    out.mkdir(parents=True, exist_ok=False)
    files = {
        "system.prmtop": "topology",
        "system.inpcrd": "coordinate",
        "system.pdb": "analysis_topology",
    }
    if recipe["branch"] == "small_molecule":
        files.update({"ligand.mol2": "ligand_mol2", "ligand.frcmod": "ligand_frcmod"})
    for name in files:
        shutil.copyfile(source / name, out / name)
    if engine == "gromacs":
        try:
            import parmed
        except ImportError as exc:
            raise ToolUnavailable(
                "PARMED_REQUIRED",
                "Install optional ParmEd for reviewed AMBER-to-GROMACS conversion.",
            ) from exc
        converted = parmed.load_file(str(out / "system.prmtop"), xyz=str(out / "system.inpcrd"))
        converted.save(str(out / "topol.top"), format="gromacs", overwrite=False)
        converted.save(str(out / "system.gro"), format="gro", overwrite=False)
        files["system.prmtop"] = "source_topology"
        files["system.inpcrd"] = "source_coordinate"
        files.update({"topol.top": "topology", "system.gro": "coordinate"})
        # Converted include files are real native output and must be bundled too.
        files.update({p.name: "topology_include" for p in out.glob("*.itp")})
    create_md_drafts(out, schemas)
    if engine in ("gromacs", "amber"):
        suffix = "mdp" if engine == "gromacs" else "mdin"
        files.update({f"{s}.{suffix}": "protocol" for s in ("em", "nvt", "npt", "md")})
    name = f"{engine}_parameters.draft.json"
    files[name] = "protocol"
    parameters = json.loads((out / name).read_text())
    shutil.copyfile(source / "native_precheck.json", out / "native_precheck.json")
    rows = [
        {
            "source": str((out / name).resolve()),
            "destination": name,
            "role": role,
            "sha256": sha(out / name),
        }
        for name, role in files.items()
    ]
    bundle = out / "inputs.tar.gz"
    with tarfile.open(bundle, "x:gz") as archive:
        for row in rows:
            archive.add(out / row["destination"], arcname=row["destination"], recursive=False)
    review = {
        "schema": "dockshift-md-system/v1",
        "engine": engine,
        "branch": recipe["branch"],
        "source_artifact_sha256": source_artifact_sha256,
        "scientist_reviewed": True,
        "reviewed_by": reviewer,
        "files": rows,
        "upload_bundle": {"source": str(bundle.resolve()), "sha256": sha(bundle)},
        "native_precheck_passed": True,
        "native_precheck_artifacts": [
            {
                "source": str((out / "native_precheck.json").resolve()),
                "sha256": sha(out / "native_precheck.json"),
            }
        ],
        "force_fields": {
            "protein": "ff14SB",
            "RNA": "OL3",
            "DNA": "OL15",
            "water": "TIP3P",
            "ligand": "GAFF2/AM1-BCC",
        },
        "components": ["protein", "water"]
        if recipe["branch"] == "biologic"
        else ["protein", "water", "ligand"],
        "ligand_net_charge": recipe.get("ligand_net_charge"),
        "status": "BLOCKED_UNTIL_NATIVE_ENGINE_PRECHECK_UPLOAD_AND_APPROVAL",
        "limitations": [
            "OpenMM topology loading is not native GROMACS/AMBER qualification.",
            (
                "Review actual energy/trajectory output selections and upload cont"
                "ract before execution."
            ),
        ],
    }
    # Conversion does not stand in for the destination engine's own precheck.
    if engine in ("gromacs", "amber"):
        review["native_precheck_passed"] = False
    path = out / "md-review.json"
    path.write_text(json.dumps(review, indent=2))
    return {
        "manifest": str(path.resolve()),
        "manifest_sha256": sha(path),
        "parameters": parameters,
        "remote_submission_performed": False,
        "scientific_acceptance": "REVIEW_REQUIRED",
    }


async def main():
    import argparse
    import uuid

    from app.config import Settings
    from app.nebius.client import NebiusClient
    from app.structural import StructuralService

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared_directory")
    parser.add_argument("--engine", choices=("gromacs", "amber", "openmm"), required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--source-artifact-sha256", required=True)
    args = parser.parse_args()
    settings = Settings()
    store = StructuralService(settings).store
    # Resolve a real file through Dockshift's existing root boundary.
    source = store.resolve_input(str(Path(args.prepared_directory) / "manifest.json")).parent
    names = {"submit_gromacs_workflow", "submit_amber_workflow", "submit_openmm_workflow"}
    schemas = {
        t.name: t.input_schema for t in await NebiusClient(settings).list_tools() if t.name in names
    }
    out = store.root / ("sealed-md-system-" + uuid.uuid4().hex)
    print(
        json.dumps(
            seal_system(
                source, out, schemas, args.engine, args.reviewed_by, args.source_artifact_sha256
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
