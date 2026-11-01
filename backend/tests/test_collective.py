"""NON-BILLABLE tests. All remote model outputs below are SYNTHETIC FIXTURES.

These tests validate contracts/orchestration, never live scientific qualification.
"""

import asyncio
import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import SecretStr

from app.config import Settings
from app.integration.artifact_io import expand_archives
from app.integration.collective import CollectiveWorkflow, audit_plan
from app.integration.md_analysis import energy_series
from app.integration.models import RunRequest, ScientificStep
from app.integration.nebius_llm import NebiusLLMProvider
from app.integration.privacy import Redactor
from app.integration.readiness import preflight_run
from app.integration.scienceclaw.adapters.base import ToolFailed, ToolUnavailable
from app.integration.scienceclaw.contracts import ArtifactRef
from app.integration.scientific_outputs import confidence_fields, validate_output
from app.integration.service import IntegrationService
from app.integration.system_builder import BuildRecipe, build_system
from app.integration.tools import DockshiftTools
from app.nebius.client import RemoteTool

FIXTURES = Path(__file__).parent / "fixtures" / "nebius"


def pdb(chains=None):
    chains = chains or {"A": "AG"}
    names = {"A": "ALA", "G": "GLY", "C": "CYS", "D": "ASP", "E": "GLU"}
    lines = []
    for chain_i, (chain, seq) in enumerate(chains.items()):
        for index, code in enumerate(seq):
            for atom, dx, dy in (("N", -1.2, 0.5), ("CA", 0, 0), ("C", 1.3, 0.5), ("O", 1.7, 1.5)):
                i = len(lines) + 1
                x, y = index * 3.8 + dx, chain_i * 4.0 + dy
                lines.append(
                    f"ATOM  {i:5d} {atom:^4s} {names[code]:3s} {chain}{index + 1:4d}    "
                    f"{x:8.3f}{y:8.3f}{0.0:8.3f}  1.00 20.00           C"
                )
    return "\n".join(lines) + "\nEND\n"


def remote(model, **data):
    return {
        "status": "SUCCEEDED",
        "artifacts": [
            {
                "filename": "synthetic.json",
                "sha256": "a" * 64,
                "hash_verified": True,
                "data": {"model_id": model, "model_version": "SYNTHETIC-TEST-ONLY", **data},
            }
        ],
    }


def config(tmp_path, **kwargs):
    return Settings(
        _env_file=None, agent_artifact_root=tmp_path, scientific_models_api_key=None, **kwargs
    )


def deps(settings):
    return (
        SimpleNamespace(search=AsyncMock()),
        SimpleNamespace(client=None, predict_activity=AsyncMock(), profile=AsyncMock()),
        SimpleNamespace(store=SimpleNamespace(resolve_input=lambda path: Path(path))),
        SimpleNamespace(
            client=SimpleNamespace(list_tools=AsyncMock(return_value=[]), call=AsyncMock())
        ),
    )


@pytest.mark.parametrize(
    "model,tool",
    [
        ("openfold2", "infer_openfold2_native"),
        ("openfold3", "infer_openfold3_native"),
        ("esmfold2", "submit_esmfold2"),
        ("alphafold3", "submit_alphafold3"),
        ("protenix-v2", "submit_protenix_v2"),
        ("boltz2", "boltz2_predict_native"),
    ],
)
def test_folding_identity_and_confidence_fixtures(tmp_path, model, tool):
    result = remote(model, pdb=pdb(), plddt=[80, 82], ptm=0.7)
    value = validate_output(tool, result, {"chains": {"A": "AG"}}, tmp_path)
    assert value["kind"] == "structure"
    assert value["native_confidence"]["plddt"] == [[80, 82]]
    assert value["model_version"] == "SYNTHETIC-TEST-ONLY"
    with pytest.raises(ToolFailed, match="identities"):
        validate_output(tool, result, {"chains": {"A": "AA"}, "_step_id": "bad-sequence"}, tmp_path)


def test_no_structure_no_version_no_confidence_cannot_pass(tmp_path):
    with pytest.raises(ToolUnavailable, match="version"):
        validate_output(
            "infer_openfold2_native",
            remote("wrong", pdb=pdb(), plddt=80),
            {"chains": {"A": "AG"}},
            tmp_path,
        )
    with pytest.raises(ToolUnavailable, match="coordinate"):
        validate_output(
            "infer_openfold2_native",
            remote("openfold2", plddt=80),
            {"chains": {"A": "AG"}},
            tmp_path,
        )
    with pytest.raises(ToolUnavailable, match="confidence"):
        validate_output(
            "infer_openfold2_native",
            remote("openfold2", pdb=pdb()),
            {"chains": {"A": "AG"}},
            tmp_path,
        )


@pytest.mark.parametrize("bad", [float("nan"), -1, 101])
def test_invalid_confidence(bad):
    with pytest.raises(ToolFailed):
        confidence_fields({"plddt": [80, bad]}, residue_count=2)
    with pytest.raises(ToolFailed, match="square"):
        confidence_fields({"pae": [[1, 2, 3], [1, 2, 3]]}, residue_count=2)


def test_complex_interface_and_native_thresholds(tmp_path):
    result = remote("boltz2", pdb=pdb({"A": "AG", "B": "AG"}), plddt=[80] * 4, iptm=0.8)
    accepted = {
        "chains": {"A": "AG", "B": "AG"},
        "interface_chains": ["A", "B"],
        "minimum_iptm": 0.7,
    }
    assert validate_output("boltz2_predict_native", result, accepted, tmp_path)["kind"] == "complex"
    with pytest.raises(ToolFailed, match="threshold"):
        validate_output(
            "boltz2_predict_native",
            result,
            {**accepted, "minimum_iptm": 0.9, "_step_id": "low-confidence"},
            tmp_path,
        )


@pytest.mark.parametrize(
    "tool,model", [("genmol_generate", "genmol"), ("molmim_run_native", "molmim")]
)
def test_generated_molecule_chemistry(tool, model, tmp_path):
    good = validate_output(
        tool, remote(model, molecules=[{"smiles": "CCO", "qed": 0.4}]), {}, tmp_path
    )
    assert good["molecules"][0]["formal_charge"] == 0
    with pytest.raises(ToolFailed):
        validate_output(tool, remote(model, molecules=["CCO.[Na+]"]), {}, tmp_path)


def test_proteinmpnn_sequence_length_and_score(tmp_path):
    result = remote("proteinmpnn", sequences=[{"sequence": "ACDE", "score": 1.2}])
    assert (
        validate_output("infer_proteinmpnn_native", result, {"binder_length": 4}, tmp_path)["kind"]
        == "sequences"
    )
    with pytest.raises(ToolFailed):
        validate_output("infer_proteinmpnn_native", result, {"binder_length": 3}, tmp_path)


@pytest.mark.parametrize(
    "tool,model",
    [
        ("submit_rfdiffusion", "rfdiffusion"),
        ("submit_rfd4_proteina", "rfd4-proteina"),
        ("submit_proteina_complexa", "proteina-complexa"),
        ("submit_boltzgen", "boltzgen"),
    ],
)
def test_backbone_design_preserves_target(tool, model, tmp_path):
    result = remote(model, pdb=pdb({"A": "AG", "B": "AG"}))
    acceptance = {"fixed_chains": {"A": "AG"}, "chain_lengths": {"A": 2, "B": 2}}
    value = validate_output(tool, result, acceptance, tmp_path)
    assert value["structures"][0]["chains"]["B"] == "AG"
    with pytest.raises(ToolUnavailable):
        validate_output(
            tool,
            result,
            {**acceptance, "fixed_chains": {"A": "AA"}, "_step_id": "wrong-target"},
            tmp_path,
        )


def test_plan_rejects_cross_branch_or_forward_reference():
    request = RunRequest(
        workflow="collective",
        steps=[
            {
                "id": "mols",
                "agent": "A3",
                "branch": "small_molecule",
                "job": {"tool": "genmol_generate", "arguments": {"smiles": "[*{10-20}]"}},
            },
            {
                "id": "binder",
                "agent": "A4",
                "branch": "biologic",
                "job": {"tool": "infer_proteinmpnn_native"},
                "bindings": [
                    {
                        "step": "mols",
                        "pointer": "/data/molecules/0/smiles",
                        "argument": "/input_pdb",
                    }
                ],
            },
        ],
    )
    with pytest.raises(ValueError, match="Cross-branch"):
        audit_plan(request)
    assert audit_plan(RunRequest(workflow="collective"))["status"] == "BLOCKED"


def test_typed_handoff_hash_and_zero_budget(tmp_path):
    settings = config(tmp_path, agent_compute_enabled=True)
    request = RunRequest(
        workflow="collective",
        budget={"approved_by": "test-scientist", "max_submissions": 0},
        steps=[
            {
                "id": "fold",
                "agent": "A2",
                "branch": "shared",
                "job": {"tool": "infer_openfold2_native"},
            }
        ],
    )
    tools = DockshiftTools(settings, request, tmp_path, "agents-" + "a" * 32, *deps(settings))
    flow = CollectiveWorkflow(tools)
    step = request.steps[0]
    flow.publish(
        step,
        {
            "kind": "structure",
            "model_id": "openfold2",
            "model_version": "SYNTHETIC",
            "sequence": "AG",
        },
    )
    downstream = ScientificStep(
        id="design",
        agent="A4",
        branch="biologic",
        job={"tool": "infer_proteinmpnn_native", "arguments": {"input_pdb": ""}},
        bindings=[{"step": "fold", "pointer": "/data/sequence", "argument": "/input_pdb"}],
    )
    assert flow.bind(downstream)[0]["input_pdb"] == "AG"
    with pytest.raises(ToolUnavailable, match="submissions"):
        flow.admit(step, {})
    ArtifactRef(**flow.records["fold"]).resolve().write_text("tampered")
    with pytest.raises(ToolFailed, match="changed"):
        flow.bind(downstream)
    tools.nebius.client.call.assert_not_called()


def test_archive_members_are_hashed_but_not_executed(tmp_path):
    settings = config(tmp_path)
    for filename in ("valid.tar.gz", "unsafe.tar.gz"):
        archive = tmp_path / filename
        with tarfile.open(archive, "w:gz") as handle:
            data = b'{"model_version":"SYNTHETIC-TEST-ONLY"}'
            info = tarfile.TarInfo(
                "results/result.json" if filename == "valid.tar.gz" else "../outside.json"
            )
            info.size = len(data)
            handle.addfile(info, io.BytesIO(data))
        result = {
            "artifacts": [
                {
                    "filename": filename,
                    "hash_verified": True,
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                }
            ]
        }
        if filename.startswith("unsafe"):
            with pytest.raises(ToolFailed, match="path"):
                expand_archives(result, tmp_path, 10000, Redactor(settings))
        else:
            expand_archives(result, tmp_path, 10000, Redactor(settings))
            assert (
                result["artifacts"][1]["parent_archive_sha256"] == result["artifacts"][0]["sha256"]
            )
            assert result["artifacts"][1]["data"]["model_version"] == "SYNTHETIC-TEST-ONLY"
    assert not (tmp_path.parent / "outside.json").exists()


@pytest.mark.parametrize(
    "engine,text",
    [
        (
            "openmm",
            '#"Time (ps)","Potential Energy (kJ/mole)","Temperature (K)"\n0,-10,300\n1,-11,301\n',
        ),
        (
            "gromacs",
            (
                '@ s0 legend "Potential"\n@ s1 legend "Temperature"\n@ s2 legend "Pr'
                'essure"\n0 -10 300 1\n1 -11 301 1\n'
            ),
        ),
        (
            "amber",
            (
                "NSTEP = 1 TIME(PS) = 0 TEMP(K) = 300\n EPtot = -10\nNSTEP = 2 TIME("
                "PS) = 1 TEMP(K) = 301\n EPtot = -11\n"
            ),
        ),
    ],
)
def test_native_energy_formats_and_units(engine, text):
    result = energy_series(text, engine)
    assert result["observations"] == 2
    assert result["convergence"] == "NOT_ASSESSED"
    assert result["potential_energy_range_kj_mol"][0] == pytest.approx(
        -11 * 4.184 if engine == "amber" else -11
    )
    with pytest.raises((ToolFailed, ValueError)):
        energy_series(text.replace("301", "nan"), engine)


def test_local_builder_preflight_never_parameterizes_or_submits(tmp_path, monkeypatch):
    import app.integration.system_builder as builder

    source = tmp_path / "assembly.pdb"
    source.write_text(pdb())
    recipe = BuildRecipe(
        branch="biologic",
        macromolecule_pdb=str(source),
        macromolecule_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        expected_chains={"A": "AG"},
        ph=7.4,
        protonation_variants=[None, None],
        assembly_reviewed_by="test-scientist",
        protocol_reviewed_by="test-scientist",
        unresolved_regions_resolution="SYNTHETIC FIXTURE; not a real construct.",
    )
    monkeypatch.setattr(builder, "native", lambda *a: pytest.fail("Preflight invoked an engine"))
    result = build_system(
        recipe, SimpleNamespace(resolve_input=Path), tmp_path / "build", execute=False
    )
    assert not result["computation_performed"] and not (tmp_path / "build").exists()
    source.write_text(source.read_text() + "REMARK changed\n")
    with pytest.raises(ValueError, match="changed"):
        build_system(recipe, SimpleNamespace(resolve_input=Path), tmp_path / "build")


def test_entire_collective_loop_keeps_all_scientific_jobs_blocked(tmp_path):
    settings = config(tmp_path)
    dependencies = deps(settings)

    async def fixture_http(request):
        assert request.url.host == "rest.uniprot.org"
        return httpx.Response(
            200,
            json={
                "primaryAccession": "O14746",
                "organism": {"taxonId": 9606},
                "genes": [{"geneName": {"value": "TERT"}}],
                "sequence": {"value": "AG"},
            },
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture_http)) as http:
            dependencies[1].client = http
            service = IntegrationService(settings, *dependencies)
            report = await service.run(RunRequest(workflow="collective"))
            assert report["status"] == "BLOCKED" and len(report["agents"]) == 8
            assert set(report["outputs"]["collective"]["branches"]) == {
                "small_molecule",
                "biologic",
            }
            assert report["ledger_integrity"]["verified"]
            assert report["llm_agents_invoked"] == 0
            assert service.report(report["run_id"]) == report
            dependencies[-1].client.call.assert_not_called()

    asyncio.run(exercise())


def test_preflight_live_schema_contract_fixtures_never_call_model(tmp_path):
    settings = config(tmp_path)
    schema = json.loads((FIXTURES / "infer_openfold3_native.json").read_text())
    args = {
        "request_id": "test",
        "inputs": [
            {
                "input_id": "test",
                "output_format": "cif",
                "molecules": [{"type": "protein", "id": "A", "sequence": "AG"}],
            }
        ],
    }
    Draft202012Validator(schema).validate(args)
    client = SimpleNamespace(
        list_tools=AsyncMock(return_value=[RemoteTool("infer_openfold3_native", "", schema)]),
        call=AsyncMock(),
    )
    request = RunRequest(
        workflow="collective",
        steps=[
            {
                "id": "fold",
                "agent": "A2",
                "branch": "shared",
                "job": {"tool": "infer_openfold3_native", "arguments": args},
            }
        ],
    )
    result = asyncio.run(preflight_run(request, client, settings))
    assert result["contracts"][0]["schema_status"] == "SCHEMA_VALID"
    assert not result["contracts"][0]["live_output_verified"]
    client.call.assert_not_called()


def test_preflight_api_auth_and_schema_errors(tmp_path, monkeypatch):
    import app.main as main

    settings = config(
        tmp_path,
        structural_rest_enabled=True,
        structural_api_token=SecretStr("test-execution-token"),
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    with TestClient(main.create_app()) as client:
        assert (
            client.post("/api/v1/agents/preflight", json={"workflow": "collective"}).status_code
            == 401
        )
        result = client.post(
            "/api/v1/agents/preflight",
            json={"workflow": "collective"},
            headers={"Authorization": "Bearer test-execution-token"},
        )
        assert result.status_code == 200 and not result.json()["submission_performed"]


def test_llm_zero_budget_never_posts(tmp_path, monkeypatch):
    provider = NebiusLLMProvider(config(tmp_path), max_calls=0)
    monkeypatch.setattr(provider, "probe", lambda: {"available": True})
    with pytest.raises(ToolUnavailable, match="LLM calls"):
        provider.chat([], [])
    assert provider.calls == 0


def test_connected_both_branches_use_real_typed_handoffs_with_fixture_models(tmp_path, monkeypatch):
    """Explicitly synthetic native outputs, not a live scientific experiment."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    from app.integration.remote import RemoteRunner

    settings = config(tmp_path, agent_compute_enabled=True)
    dependencies = deps(settings)
    dependencies[1].predict_activity.return_value = SimpleNamespace(
        model_dump=lambda **kw: {"predictions": []}
    )
    dependencies[1].profile.return_value = SimpleNamespace(model_dump=lambda **kw: {"profiles": []})
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    AllChem.EmbedMolecule(mol, randomSeed=2026)
    mol = Chem.RemoveHs(mol)
    reference = tmp_path / "reference.sdf"
    with Chem.SDWriter(str(reference)) as writer:
        writer.write(mol)
    target_structure = pdb({"A": "AG", "B": "AG"})
    steps = [
        {
            "id": "fold",
            "agent": "A2",
            "branch": "shared",
            "job": {
                "tool": "infer_openfold3_native",
                "arguments": {
                    "request_id": "test",
                    "inputs": [
                        {
                            "input_id": "test",
                            "output_format": "cif",
                            "molecules": [
                                {"id": "A", "type": "protein", "sequence": "AG"},
                                {"id": "B", "type": "protein", "sequence": "AG"},
                            ],
                        }
                    ],
                },
            },
            "acceptance": {"reviewed_by": "test-scientist", "chains": {"A": "AG", "B": "AG"}},
        },
        {
            "id": "molecules",
            "agent": "A3",
            "branch": "small_molecule",
            "job": {
                "tool": "genmol_generate",
                "arguments": {"smiles": "[*{10-20}]", "num_molecules": 1},
            },
            "acceptance": {"reviewed_by": "test-scientist"},
        },
        {
            "id": "binder",
            "agent": "A4",
            "branch": "biologic",
            "job": {
                "tool": "infer_proteinmpnn_native",
                "arguments": {"input_pdb": "", "input_pdb_chains": ["B"]},
            },
            "acceptance": {
                "reviewed_by": "test-scientist",
                "binder_length": 2,
                "fixed_target_chains": ["A"],
            },
            "bindings": [
                {
                    "step": "fold",
                    "pointer": "/data/structures/0/structure",
                    "argument": "/input_pdb",
                }
            ],
        },
        {
            "id": "control",
            "agent": "A5a",
            "branch": "small_molecule",
            "job": {"tool": "infer_diffdock_native", "arguments": {"protein": "", "ligand": "CCO"}},
            "acceptance": {
                "reviewed_by": "test-scientist",
                "control": True,
                "reference_sdf": str(reference),
                "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
            },
            "bindings": [
                {"step": "fold", "pointer": "/data/structures/0/structure", "argument": "/protein"}
            ],
        },
        {
            "id": "complex",
            "agent": "A5b",
            "branch": "biologic",
            "job": {
                "tool": "boltz2_predict_native",
                "arguments": {
                    "polymers": [
                        {"id": "A", "molecule_type": "protein", "sequence": "AG"},
                        {"id": "B", "molecule_type": "protein", "sequence": ""},
                    ]
                },
            },
            "acceptance": {
                "reviewed_by": "test-scientist",
                "chains": {"A": "AG", "B": "AG"},
                "interface_chains": ["A", "B"],
            },
            "bindings": [
                {
                    "step": "binder",
                    "pointer": "/data/sequences/0/sequence",
                    "argument": "/polymers/1/sequence",
                }
            ],
        },
    ]
    observed = []

    async def fixture_execute(self, agent, tool, arguments, operation_id=None):
        observed.append((agent, tool, arguments))
        if agent == "fold":
            return remote("openfold3", pdb=target_structure, plddt=[80] * 4, ptm=0.8)
        if agent == "molecules":
            return remote("genmol", molecules=["CCO"])
        if agent == "binder":
            assert arguments["input_pdb"] == target_structure
            return remote("proteinmpnn", sequences=[{"sequence": "AG", "score": 1.1}])
        if agent == "control":
            return remote(
                "diffdock", ligand_positions=[Chem.MolToMolBlock(mol)], position_confidence=[0.5]
            )
        assert arguments["polymers"][1]["sequence"] == "AG"
        return remote("boltz2", pdb=target_structure, plddt=[80] * 4, iptm=0.8)

    monkeypatch.setattr(RemoteRunner, "execute", fixture_execute)

    async def fixture_http(request):
        return httpx.Response(
            200,
            json={
                "primaryAccession": "O14746",
                "organism": {"taxonId": 9606},
                "genes": [{"geneName": {"value": "TERT"}}],
                "sequence": {"value": "AG"},
            },
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture_http)) as http:
            dependencies[1].client = http
            service = IntegrationService(settings, *dependencies)
            report = await service.run(
                RunRequest(
                    workflow="collective",
                    steps=steps,
                    budget={"max_submissions": 5, "approved_by": "test-scientist"},
                )
            )
            assert report["status"] == "BLOCKED"
            statuses = {a["agent"]: a["scientific_status"] for a in report["agents"]}
            assert all(
                statuses[a] == "SUCCEEDED" for a in ("A1", "A2", "A3", "A4", "A5a", "A5b", "A7")
            ), statuses
            assert statuses["A6"] == "BLOCKED"
            assert len(observed) == 5
            assert (
                report["outputs"]["collective"]["steps"]["complex"]["validation"]["kind"]
                == "complex"
            )
            assert service.report(report["run_id"]) == report
            # An immutable continuation imports the real typed results, never reruns them.
            imported = await service.run(
                RunRequest(
                    workflow="collective",
                    steps=steps,
                    source_run=report["run_id"],
                    resume_only=True,
                )
            )
            assert len(observed) == 5
            assert imported["status"] == "BLOCKED"
            assert service.report(imported["run_id"]) == imported

    asyncio.run(exercise())


def test_input_upload_gate_never_reserves_or_transfers(tmp_path):
    from app.integration.input_upload import upload_input

    client = SimpleNamespace(list_tools=AsyncMock(), call=AsyncMock())
    with pytest.raises(ToolUnavailable, match="opt-in"):
        asyncio.run(
            upload_input(
                client,
                config(tmp_path),
                tmp_path / "nonexistent",
                "openmm",
                "application/gzip",
                "test-reviewer",
            )
        )
    client.list_tools.assert_not_called()
    client.call.assert_not_called()


def test_completed_compute_with_pending_result_delivery_remains_pending(tmp_path):
    from app.integration.remote import RemoteRunner

    settings = config(tmp_path, agent_remote_wait_seconds=0)
    calls = []

    async def lifecycle(tool, arguments, **kwargs):
        calls.append(tool)
        if tool == "get_operation":
            return {"operation": {"id": "op-fixture", "status": "SUCCEEDED"}}
        assert tool == "get_operation_result"
        return {"error": {"code": "RESULT_NOT_READY", "operation_id": "op-fixture"}}

    client = SimpleNamespace(
        list_tools=AsyncMock(return_value=[RemoteTool("genmol_generate", "", {"type": "object"})]),
        call=lifecycle,
    )
    result = asyncio.run(
        RemoteRunner(settings, client, tmp_path, "agents-" + "b" * 32).execute(
            "molecules", "genmol_generate", {}, "op-fixture"
        )
    )
    assert result["status"] == "PENDING"
    assert calls == ["get_operation", "get_operation_result"]


def test_generation_does_not_succeed_when_native_count_is_incomplete(tmp_path):
    with pytest.raises(ToolUnavailable, match="requested number"):
        validate_output(
            "genmol_generate",
            remote("genmol", molecules=["CCO"]),
            {"requested_molecules": 2},
            tmp_path,
        )
