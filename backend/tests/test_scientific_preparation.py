"""Synthetic local geometry and frozen native schemas; no scientific jobs submitted."""

import asyncio
import copy
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from app.config import Settings
from app.integration.md_execution import audit_system, verify_archive
from app.integration.md_protocols import STEPS, create_md_drafts, validate_md_result
from app.integration.models import RunRequest
from app.integration.scienceclaw.adapters.base import ToolUnavailable
from app.integration.scientific_preparation import structure_inputs, validate_diffdock
from app.integration.service import IntegrationService
from app.nebius.client import RemoteTool
from app.qsar import QsarService

SMILES = r"C/C(=C\C(=O)Nc1ccccc1C(=O)O)c1ccc2ccccc2c1"
FIXTURES = Path(__file__).parent / "fixtures" / "nebius"


def schemas():
    return {p.stem: json.loads(p.read_text()) for p in FIXTURES.glob("*.json")}


def synthetic_structure():
    mol = Chem.AddHs(Chem.MolFromSmiles(SMILES))
    assert AllChem.EmbedMolecule(mol, randomSeed=2026) == 0
    mol = Chem.RemoveHs(mol)
    for i, atom in enumerate(mol.GetAtoms()):
        atom.SetMonomerInfo(
            Chem.AtomPDBResidueInfo(
                atomName=f"{atom.GetSymbol()}{i + 1}".rjust(4),
                residueName="55C",
                residueNumber=1201,
                chainId="A",
                isHeteroAtom=True,
            )
        )
    ligand = Chem.MolToPDBBlock(mol)
    receptor = (
        "ATOM      1  CA  ALA A 100       1.000   2.000   3.000  1.00 20.00           C\n"
        "ATOM      2  CA  GLY A 102       4.000   5.000   6.000  1.00 20.00           C\n"
    )
    pdb = (
        receptor
        + "\n".join(line for line in ligand.splitlines() if line.startswith("HETATM"))
        + "\nEND\n"
    )
    ccd = {"chem_comp": {"id": "55C"}, "rcsb_chem_comp_descriptor": {"SMILES_stereo": SMILES}}
    return pdb, ccd, mol


def test_deposited_input_checks_and_no_cropping():
    pdb, ccd, _ = synthetic_structure()
    receptor, _, ligand, report = structure_inputs(pdb, ccd, "A")
    assert report["ligand_heavy_atoms"] == 25
    assert report["protein_atoms"] == 2
    assert report["internal_residue_number_gaps"] == [[101, 101]]
    assert "55C" not in receptor
    assert Chem.MolToInchiKey(ligand) == Chem.MolToInchiKey(Chem.MolFromSmiles(SMILES))
    assert report["ccd_formal_charge"] == 0
    wrong = copy.deepcopy(ccd)
    wrong["rcsb_chem_comp_descriptor"]["SMILES_stereo"] = "CCO"
    with pytest.raises(ValueError, match="incomplete"):
        structure_inputs(pdb, wrong, "A")


def test_native_md_protocol_drafts_are_not_a_prepared_system(tmp_path):
    report = create_md_drafts(tmp_path, schemas())
    assert report["protocols_schema_valid"]
    assert report["status"] == "BLOCKED" and not report["simulation_executed"]
    assert report["force_field_proposal"]["selected_ligand_net_charge"] is None
    assert not list(tmp_path.glob("*.prmtop")) and not list(tmp_path.glob("*.mol2"))
    assert "gen-vel = no" in (tmp_path / "md.mdp").read_text()
    assert "nstlim=500000" in (tmp_path / "md.mdin").read_text()
    gromacs = json.loads((tmp_path / "gromacs_parameters.draft.json").read_text())
    assert len(gromacs["jobs"][0]["steps"]) == 8
    assert gromacs["max_wall_seconds"] == 3600
    assert STEPS["md"] * 0.002 == 1000


@pytest.mark.parametrize("shift,expected", [(0, "PASS"), (10, "FAIL")])
def test_real_pose_geometry_checks_do_not_align_away_bad_redocking(tmp_path, shift, expected):
    _, _, mol = synthetic_structure()
    reference = tmp_path / "reference.sdf"
    writer = Chem.SDWriter(str(reference))
    writer.write(mol)
    writer.close()
    pose = Chem.Mol(mol)
    conformer = pose.GetConformer()
    for i in range(pose.GetNumAtoms()):
        x, y, z = conformer.GetAtomPosition(i)
        conformer.SetAtomPosition(i, (x + shift, y, z))
    result = {
        "artifacts": [
            {
                "hash_verified": True,
                "data": {
                    "ligand_positions": [Chem.MolToMolBlock(pose)],
                    "position_confidence": [0.123],
                },
            }
        ]
    }
    checked = validate_diffdock(result, SMILES, reference)
    assert checked["reference_redocking_qc"] == expected
    assert checked["poses"][0]["same_frame_symmetry_corrected_rmsd_angstrom"] == pytest.approx(
        shift, abs=0.001
    )
    assert not checked["affinity_computed"]
    result["artifacts"][0]["data"]["position_confidence"] = [float("nan")]
    with pytest.raises(ValueError, match="Non-finite"):
        validate_diffdock(result, SMILES, reference)


def test_successful_md_receipt_without_trajectory_cannot_pass():
    document = {
        "status": "succeeded",
        "engine_version": "fixture-version",
        "jobs": [
            {
                "steps": [
                    {"id": name, "status": "succeeded", "completed_steps": n}
                    for name, n in STEPS.items()
                ]
            }
        ],
    }
    result = {"artifacts": [{"filename": "result.json", "hash_verified": True, "data": document}]}
    with pytest.raises(ToolUnavailable, match="MD_TRAJECTORY_REQUIRED"):
        validate_md_result(result, STEPS)
    result["artifacts"].append({"filename": "md.xtc", "hash_verified": True, "data": None})
    checked = validate_md_result(result, STEPS)
    assert checked["convergence"] == "NOT_ASSESSED"
    assert checked["binding_stability"] == "NOT_ASSESSED"
    document["jobs"][0]["steps"][-1]["completed_steps"] -= 1
    with pytest.raises(ToolUnavailable, match="MD_STEP_COUNT_UNVERIFIED"):
        validate_md_result(result, STEPS)


def test_metadata_cannot_substitute_for_ligand_parameters():
    manifest = {
        "schema": "dockshift-md-system/v1",
        "engine": "openmm",
        "scientist_reviewed": True,
        "force_fields": {k: "declared-only" for k in ["protein", "RNA", "DNA", "ligand", "water"]},
        "files": [],
    }
    with pytest.raises(ToolUnavailable, match="MD_PARAMETERS_MISSING"):
        audit_system(manifest, None)


def test_archive_link_rejected_without_extracting_anything(tmp_path):
    import hashlib

    bundle = tmp_path / "bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        item = tarfile.TarInfo("topol.top")
        item.type = tarfile.SYMTYPE
        item.linkname = "../outside"
        archive.addfile(item)
    store = SimpleNamespace(resolve_input=lambda source: Path(source))
    manifest = {
        "upload_bundle": {
            "source": str(bundle),
            "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        }
    }
    with pytest.raises(ValueError, match="Unsafe"):
        verify_archive(manifest, store, [], 1000)
    assert not (tmp_path / "topol.top").exists()


def test_preparation_runtime_cannot_submit_science_or_invoke_llm(tmp_path, monkeypatch):
    import app.integration.runtime as runtime

    class ForbiddenLLM:
        def __init__(self, settings):
            raise AssertionError("Preparation must not construct an LLM provider")

    monkeypatch.setattr(runtime, "NebiusLLMProvider", ForbiddenLLM)
    pdb, ccd, _ = synthetic_structure()
    contracts = schemas()

    async def exercise():
        def primary(request):
            if request.url.path.endswith("/9Q14.pdb"):
                return httpx.Response(200, text=pdb)
            if "/polymer_entity/" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "rcsb_polymer_entity_container_identifiers": {"uniprot_ids": ["O14746"]},
                        "entity_poly": {"pdbx_strand_id": "A"},
                    },
                )
            if request.url.path.endswith("/55C"):
                return httpx.Response(200, json=ccd)
            return httpx.Response(
                200,
                json={
                    "struct": {"title": "Synthetic test fixture"},
                    "rcsb_entry_container_identifiers": {"polymer_entity_ids": ["1"]},
                },
            )

        async def read_model(tool, args, **kwargs):
            assert tool == "get_model_schema", "Preparation attempted remote scientific execution"
            return {"model_id": args["model_id"], "qualification": "test-fixture"}

        mcp = SimpleNamespace(
            list_tools=AsyncMock(
                return_value=[RemoteTool(name, "", schema) for name, schema in contracts.items()]
            ),
            call=AsyncMock(side_effect=read_model),
        )
        config = Settings(
            _env_file=None,
            agent_artifact_root=tmp_path,
            scientific_models_api_key=None,
            agent_llm_enabled=True,
            nebius_llm_model="never-call-this-model",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(primary)) as http:
            service = IntegrationService(
                config, None, QsarService(http, config), None, SimpleNamespace(client=mcp)
            )
            report = await service.run(RunRequest(workflow="preparation", use_nebius_llm=True))
            assert report["status"] == "BLOCKED"
            assert report["llm_agents_invoked"] == 0
            assert report["computational_evidence"] == []
            assert report["outputs"]["docking_preparation"]["schema_valid"]
            assert not report["outputs"]["docking_preparation"]["remote_job_submitted"]
            assert report["outputs"]["md_preparation"]["protocols_schema_valid"]
            assert report["ledger_integrity"]["verified"]
            assert len(report["agents"]) == 8
            assert service.report(report["run_id"]) == report

    asyncio.run(exercise())


def test_md_expected_steps_are_bound_to_submitted_protocol(tmp_path):
    from app.integration.md_execution import expected_step_counts

    (tmp_path / "md.mdp").write_text("integrator = md\nnsteps = 1234\n")
    store = SimpleNamespace(resolve_input=lambda source: Path(source))
    manifest = {
        "engine": "gromacs",
        "files": [{"source": str(tmp_path / "md.mdp"), "destination": "md.mdp"}],
    }
    arguments = {
        "request": {
            "parameters": {
                "jobs": [
                    {
                        "steps": [
                            {
                                "id": "compile",
                                "command": "grompp",
                                "args": ["-f", "md.mdp", "-o", "md.tpr"],
                            },
                            {"id": "md-run", "command": "mdrun", "args": ["-s", "md.tpr"]},
                        ]
                    }
                ]
            }
        }
    }
    assert expected_step_counts(manifest, arguments, store) == {"md-run": 1234}
    manifest["expected_steps"] = {"md-run": 1233}
    with pytest.raises(ValueError, match="differ"):
        expected_step_counts(manifest, arguments, store)
    with pytest.raises(ValueError, match="Explicit positive"):
        validate_md_result({"artifacts": []}, {})


def test_binary_md_evidence_is_preserved_without_json_or_convergence_claims(tmp_path, monkeypatch):
    from test_managed_research import configure, fake_mcp, transport_patch

    from app.integration.remote import RemoteRunner

    data = b"\x00\x01synthetic-trajectory-test-bytes\x02"
    pointer, _ = transport_patch(monkeypatch, data)
    pointer["media_type"] = "chemical/x-gromacs-xtc"
    runner = RemoteRunner(configure(tmp_path), fake_mcp(pointer), tmp_path, "test-run")
    artifact = asyncio.run(runner.retrieve("A6", pointer, 0))
    assert artifact["filename"].endswith(".xtc")
    assert artifact["data"] is None and not artifact["format_validated"]
    assert artifact["hash_verified"]
    assert (tmp_path / artifact["filename"]).read_bytes() == data
