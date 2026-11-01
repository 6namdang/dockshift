"""MD admission adapter: reviewed, hashed native inputs before expensive execution."""

import hashlib
import json
import math
import re
import tarfile
from pathlib import PurePosixPath

from .md_protocols import validate_md_result
from .remote import RemoteRunner, objects
from .scienceclaw.adapters.base import ToolUnavailable

MD_TOOLS = {
    "gromacs": "submit_gromacs_workflow",
    "amber": "submit_amber_workflow",
    "openmm": "submit_openmm_workflow",
}


def audit_system(manifest, store):
    """Check actual files and declarations; this is not an engine/force-field validation."""
    if manifest.get("schema") != "dockshift-md-system/v1":
        raise ValueError("Unsupported local MD system manifest")
    if manifest.get("engine") not in MD_TOOLS:
        raise ValueError("Unsupported MD engine")
    if not manifest.get("scientist_reviewed"):
        raise ToolUnavailable(
            "MD_REVIEW_REQUIRED", "Prepared physical system needs scientist review."
        )
    biologic = manifest.get("branch") == "biologic"
    components = manifest.get(
        "components",
        ["protein", "water"] if biologic else ["protein", "RNA", "DNA", "ligand", "water"],
    )
    if not components or not all(manifest.get("force_fields", {}).get(k) for k in components):
        raise ToolUnavailable(
            "FORCE_FIELDS_REQUIRED", "Explicit component force fields are required."
        )
    roles, verified, destinations = {}, [], set()
    for item in manifest.get("files", []):
        destination = PurePosixPath(item["destination"])
        if destination.is_absolute() or ".." in destination.parts or "\\" in str(destination):
            raise ValueError("Unsafe MD bundle destination")
        if str(destination) in destinations:
            raise ValueError("Duplicate MD bundle destination")
        destinations.add(str(destination))
        path = store.resolve_input(item["source"])
        data = path.read_bytes()
        if not data or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("MD input bytes do not match the reviewed hash")
        roles.setdefault(item["role"], []).append(path)
        verified.append(
            {
                "destination": str(destination),
                "sha256": item["sha256"],
                "size_bytes": len(data),
                "role": item["role"],
            }
        )
    required = ("coordinate", "topology", "protocol") + (
        () if biologic else ("ligand_mol2", "ligand_frcmod")
    )
    for role in required:
        if role not in roles:
            raise ToolUnavailable("MD_PARAMETERS_MISSING", f"MD bundle has no actual {role} file.")
    charges = []
    if not biologic:
        mol2 = roles["ligand_mol2"][0].read_text()
        if "@<TRIPOS>ATOM" not in mol2 or "@<TRIPOS>BOND" not in mol2:
            raise ValueError("Ligand MOL2 lacks atoms/bonds/partial charges")
        atom_section = mol2.split("@<TRIPOS>ATOM", 1)[1].split("@<TRIPOS>", 1)[0]
        charges = [float(line.split()[8]) for line in atom_section.splitlines() if line.strip()]
        selected_charge = manifest.get("ligand_net_charge")
        if isinstance(selected_charge, bool) or not isinstance(selected_charge, int):
            raise ToolUnavailable("LIGAND_CHARGE_REQUIRED", "A reviewed ligand charge is required.")
        if (
            not charges
            or not all(math.isfinite(v) for v in charges)
            or abs(sum(charges) - selected_charge) > 0.001
        ):
            raise ValueError("MOL2 partial charges do not sum to the reviewed ligand charge")
        frcmod = roles["ligand_frcmod"][0].read_text()
        if not all(section in frcmod for section in ("MASS", "BOND", "ANGLE", "DIHE", "NONBON")):
            raise ValueError("Ligand FRCMOD is missing parameter sections")
        if "ATTN" in frcmod.upper() or "NEED REVISION" in frcmod.upper():
            raise ToolUnavailable(
                "LIGAND_PARAMETERS_UNRESOLVED", "Unresolved FRCMOD parameters need review."
            )
    topology = roles["topology"][0].read_text()
    if manifest["engine"] in {"amber", "openmm"}:
        if not all(
            flag in topology
            for flag in ("%FLAG POINTERS", "%FLAG ATOM_NAME", "%FLAG CHARGE", "%FLAG MASS")
        ):
            raise ValueError("AMBER PRMTOP is not a parameterized native topology")
    elif "[ molecules ]" not in topology or "[ system ]" not in topology:
        raise ValueError("GROMACS topology is missing system/molecule declarations")
    return {
        "status": "FILES_HASH_VERIFIED",
        "files": verified,
        "ligand_charge_sum": sum(charges),
        "scientific_validity": "SCIENTIST_REVIEW_REQUIRED",
        "limitations": [
            "Header and charge checks do not replace native topology preprocessing.",
            "Atom ordering, include closure, missing residues and parameters need native precheck.",
        ],
    }


def verify_archive(manifest, store, verified_files, byte_limit):
    bundle = manifest.get("upload_bundle")
    if not bundle:
        raise ToolUnavailable(
            "MD_BUNDLE_REQUIRED", "The actual reviewed upload archive is missing."
        )
    path = store.resolve_input(bundle["source"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != bundle["sha256"]:
        raise ValueError("MD upload archive hash changed")
    expected = {row["destination"]: row["sha256"] for row in verified_files}
    observed, total = {}, 0
    with tarfile.open(path, mode="r:gz") as archive:
        for member in archive:
            destination = PurePosixPath(member.name)
            if (
                destination.is_absolute()
                or ".." in destination.parts
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("Unsafe MD upload archive member")
            if member.isdir():
                continue
            if not member.isfile() or str(destination) in observed:
                raise ValueError("Unsupported or duplicate MD archive member")
            total += member.size
            if total > byte_limit or len(observed) >= 256:
                raise ToolUnavailable(
                    "MD_BUNDLE_SIZE_LIMIT", "MD archive exceeds configured audit limits."
                )
            handle = archive.extractfile(member)
            observed[str(destination)] = hashlib.sha256(handle.read()).hexdigest()
    if observed != expected:
        raise ValueError("MD upload archive does not contain exactly the reviewed input bytes")
    return bundle["sha256"]


def expected_step_counts(manifest, arguments, store):
    """Bind completion assertions to the actual submitted native inputs."""
    jobs = arguments.get("request", {}).get("parameters", {}).get("jobs", [])
    if len(jobs) != 1:
        raise ValueError("Exactly one reviewed native MD job is required")
    expected = {}
    engine = manifest["engine"]
    if engine == "openmm":
        expected = {s["id"]: s.get("steps") for s in jobs[0]["steps"] if s["kind"] != "minimize"}
    elif engine == "amber":
        expected = {
            s["id"]: s.get("expected_nsteps")
            for s in jobs[0]["steps"]
            if s.get("task") == "dynamics"
        }
    else:
        files = {row["destination"]: row for row in manifest["files"]}
        compiled = {}
        for step in jobs[0]["steps"]:
            args = step.get("args", [])
            if any(not isinstance(arg, str) for arg in args):
                raise ToolUnavailable(
                    "MD_ARGV_REVIEW_REQUIRED", "MD audit requires explicit native argv."
                )
            if step["command"] == "grompp":
                source = args[args.index("-f") + 1]
                output = args[args.index("-o") + 1]
                protocol = store.resolve_input(files[source]["source"]).read_text()
                values = dict(re.findall(r"^\s*([a-zA-Z_-]+)\s*=\s*([^;\n]+)", protocol, re.M))
                if values.get("integrator", "").strip() in {"md", "sd", "bd"}:
                    compiled[output] = int(values["nsteps"].strip())
            elif step["command"] == "mdrun":
                native_tpr = args[args.index("-s") + 1]
                if native_tpr in compiled:
                    expected[step["id"]] = compiled[native_tpr]
    if not expected or any(
        isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in expected.values()
    ):
        raise ValueError("Cannot verify the requested native dynamics step counts")
    if manifest.get("expected_steps") is not None and manifest["expected_steps"] != expected:
        raise ValueError("Review step counts differ from actual native scientific inputs")
    return expected


async def execute_md(tools, job, label="A6_md", review=None):
    review = review or tools.request.md_review
    if review is None:
        raise ToolUnavailable(
            "MD_SYSTEM_REVIEW_REQUIRED", "A reviewed native MD system manifest is required."
        )
    operation_id = job.operation_id
    if not operation_id and not tools.settings.agent_compute_enabled:
        raise ToolUnavailable(
            "COMPUTE_APPROVAL_REQUIRED", "MD remains disabled until explicitly authorized."
        )
    source = tools.structural.store.resolve_input(review.manifest.path)
    if hashlib.sha256(source.read_bytes()).hexdigest() != review.manifest_sha256:
        raise ValueError("MD review manifest changed")
    manifest = json.loads(source.read_text())
    if job.tool != MD_TOOLS.get(manifest.get("engine")):
        raise ValueError("Reviewed MD engine does not match requested model")
    audit = audit_system(manifest, tools.structural.store)
    expected = expected_step_counts(manifest, job.arguments, tools.structural.store)
    # Native precheck evidence must be supplied and audited by the scientist. A boolean
    # admission switch alone does not supply parameterization, topology or convergence.
    if not manifest.get("native_precheck_passed") or not manifest.get("native_precheck_artifacts"):
        raise ToolUnavailable(
            "NATIVE_MD_PRECHECK_REQUIRED", "Native preprocessing evidence is missing."
        )
    for item in manifest["native_precheck_artifacts"]:
        path = tools.structural.store.resolve_input(item["source"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Native precheck artifact hash mismatch")
    bundle_hash = verify_archive(
        manifest, tools.structural.store, audit["files"], tools.settings.agent_max_artifact_bytes
    )
    pointer = job.arguments.get("request", {}).get("input_manifest")
    if not isinstance(pointer, dict):
        raise ToolUnavailable(
            "NEBIUS_INPUT_MANIFEST_REQUIRED", "An actual uploaded manifest is required."
        )
    runner = RemoteRunner(tools.settings, tools.nebius.client, tools.out, tools.run_id)
    uploaded = await runner.retrieve(label + "_input_manifest", pointer, 0)
    if not isinstance(uploaded.get("data"), dict) or not any(
        item.get("sha256") == bundle_hash for item in objects(uploaded["data"])
    ):
        raise ValueError("Nebius input manifest does not bind the reviewed local upload archive")
    audit["remote_input_manifest_sha256"] = uploaded["sha256"]
    audit["upload_bundle_sha256"] = bundle_hash
    tools.verified_outputs["md_input_audit"] = audit
    with (tools.out / (label + "_review.json")).open("x") as f:
        json.dump(
            {
                "audit": audit,
                "approved_by": review.approved_by,
                "manifest_sha256": review.manifest_sha256,
            },
            f,
            indent=2,
        )
    remote = await RemoteRunner(
        tools.settings, tools.nebius.client, tools.out, tools.run_id
    ).execute(label, job.tool, job.arguments, operation_id)
    tools.verified_outputs["md_operation"] = {k: v for k, v in remote.items() if k != "artifacts"}
    if remote["status"] == "PENDING":
        return {
            "_status": "BLOCKED",
            "_error_code": "REMOTE_OPERATION_PENDING",
            **remote,
        }, "MD operation pending."
    from .artifact_io import expand_archives
    from .md_analysis import energy_series, trajectory_checks

    expand_archives(remote, tools.out, tools.settings.agent_max_artifact_bytes, tools.redact)
    validation = validate_md_result(remote, expected)
    selection = manifest.get("output_selection", {})

    def selected(key):
        name = selection.get(key)
        rows = [
            a
            for a in remote["artifacts"]
            if name and name in (a.get("source_member"), a.get("native_name"), a.get("filename"))
        ]
        if len(rows) != 1:
            raise ToolUnavailable(
                "MD_OUTPUT_SELECTION_REQUIRED",
                "Select exact native trajectory and energy artifacts for analysis.",
            )
        return tools.out / rows[0]["filename"]

    topology_rows = [r for r in manifest["files"] if r["role"] == "analysis_topology"]
    if len(topology_rows) != 1:
        raise ToolUnavailable(
            "ANALYSIS_TOPOLOGY_REQUIRED", "A matched analysis PDB/PRMTOP is required."
        )
    topology_path = tools.structural.store.resolve_input(topology_rows[0]["source"])
    validation["energies"] = energy_series(selected("energies").read_text(), manifest["engine"])
    validation["trajectory"] = trajectory_checks(selected("trajectory"), topology_path)
    tools.verified_outputs.setdefault("md_branches", {})[label] = {
        "operation": remote,
        "validation": validation,
        "input_audit": audit,
    }
    tools.verified_outputs["md_validation"] = validation
    from .scienceclaw.contracts import AgentEvent, ArtifactRef, WorkerState

    validation_path = tools.out / (label + "_native_validation.json")
    validation_path.write_text(json.dumps(validation, indent=2))
    tools.ledger.append(
        AgentEvent(
            run_id=tools.run_id,
            agent="A6." + label,
            event_type="MD_NATIVE_COMPLETION_CHECKED",
            status=WorkerState.SUCCEEDED,
            outputs=[ArtifactRef.of(validation_path, "md_execution_checks")],
            tool_versions={manifest["engine"]: validation["engine_version"]},
            input_artifact_hashes=[review.manifest_sha256],
            note=(
                "Native execution/format checks passed; physical convergence and b"
                "inding stability remain unassessed."
            ),
        )
    )
    # Even validated native completion is not physical convergence.
    return {
        "_status": "BLOCKED",
        "_error_code": "MD_CONVERGENCE_REVIEW_REQUIRED",
        "validation": validation,
    }, "MD execution evidence verified; convergence requires scientist analysis."
