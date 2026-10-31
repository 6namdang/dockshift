"""Official AlphaFold 3 local-runner adapter."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.config import BACKEND_DIR, Settings
from app.structural.artifacts import ArtifactStore
from app.structural.errors import ParseError, PrerequisiteError
from app.structural.execution import LocalExecutionBackend
from app.structural.models import (
    AlphaFold3Request,
    AlphaFold3Result,
    ArtifactRef,
    RunStatus,
)


def _entity_id(index: int) -> str:
    value = index + 1
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def build_af3_input(request: AlphaFold3Request) -> dict[str, Any]:
    sequences: list[dict[str, Any]] = []
    entity_index = 0
    for protein in request.proteins:
        payload: dict[str, Any] = {
            "id": _entity_id(entity_index),
            "sequence": protein.sequence,
        }
        if protein.unpaired_msa is not None:
            payload["unpairedMsa"] = protein.unpaired_msa
        if protein.paired_msa is not None:
            payload["pairedMsa"] = protein.paired_msa
        if protein.templates is not None:
            payload["templates"] = [
                {
                    "mmcif": template.mmcif,
                    "queryIndices": template.query_indices,
                    "templateIndices": template.template_indices,
                }
                for template in protein.templates
            ]
        sequences.append({"protein": payload})
        entity_index += 1
    for smiles in request.ligand_smiles:
        sequences.append({"ligand": {"id": _entity_id(entity_index), "smiles": smiles.strip()}})
        entity_index += 1
    return {
        "name": request.job_name,
        "modelSeeds": request.seeds,
        "sequences": sequences,
        "dialect": "alphafold3",
        "version": 1,
    }


def _configured_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return (path if path.is_absolute() else BACKEND_DIR / path).expanduser().resolve()


def discover_top_ranked_structure(output_dir: Path, job_name: str) -> Path | None:
    """Find only an official root-level AF3 top model, never a sample fallback."""
    variants = list(
        dict.fromkeys(
            (
                job_name,
                job_name.lower(),
                re.sub(r"[^a-z0-9_-]+", "_", job_name.lower()).strip("_"),
                re.sub(r"[^a-z0-9]+", "_", job_name.lower()).strip("_"),
            )
        )
    )
    roots = [output_dir / name for name in variants if (output_dir / name).is_dir()]
    roots.append(output_dir)
    suffixes = (".cif", ".mmcif", ".pdb")
    for root in roots:
        stems = list(dict.fromkeys((*variants, root.name, root.name.lower())))
        for stem in stems:
            for suffix in suffixes:
                candidate = root / f"{stem}_model{suffix}"
                if candidate.is_file():
                    return candidate
    return None


class AlphaFold3Adapter:
    def __init__(
        self, settings: Settings, store: ArtifactStore, backend: LocalExecutionBackend
    ) -> None:
        self.settings = settings
        self.store = store
        self.backend = backend

    def prerequisites(self) -> tuple[Path, Path, Path]:
        script = _configured_path(self.settings.alphafold3_script)
        model_dir = _configured_path(self.settings.alphafold3_model_dir)
        database_dir = _configured_path(self.settings.alphafold3_database_dir)
        missing: list[str] = []
        if script is None or not script.is_file():
            missing.append("ALPHAFOLD3_SCRIPT (official run_alphafold.py)")
        if model_dir is None or not model_dir.is_dir():
            missing.append("ALPHAFOLD3_MODEL_DIR (licensed model parameters)")
        if database_dir is None or not database_dir.is_dir():
            missing.append("ALPHAFOLD3_DATABASE_DIR (official databases)")
        if missing:
            raise PrerequisiteError(
                "AlphaFold 3 cannot run until all external official assets are configured.",
                details={"missing": missing, "fallback_used": False},
            )
        return script, model_dir, database_dir

    async def run(self, request: AlphaFold3Request) -> AlphaFold3Result:
        script, model_dir, database_dir = self.prerequisites()
        workspace = self.store.create_run("alphafold3")
        input_path = workspace.path / "input.json"
        input_path.write_text(
            json.dumps(build_af3_input(request), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        output_dir = workspace.path / "output"
        output_dir.mkdir()
        output = await self.backend.run(
            self.settings.alphafold3_python_executable,
            [
                str(script),
                f"--json_path={input_path}",
                f"--model_dir={model_dir}",
                f"--db_dir={database_dir}",
                f"--output_dir={output_dir}",
            ],
            workspace,
            label="AlphaFold-3",
        )
        structures = self._refs(output_dir, {".cif", ".mmcif", ".pdb"})
        top_ranked_path = discover_top_ranked_structure(output_dir, request.job_name)
        confidence_paths = [
            path
            for path in output_dir.rglob("*.json")
            if any(word in path.name.lower() for word in ("confidence", "summary"))
        ]
        confidence_refs = [
            self.store.ref(path, media_type="application/json") for path in confidence_paths
        ]
        if not structures:
            raise ParseError(
                "AlphaFold 3 completed but no CIF, mmCIF, or PDB output was discovered.",
                details={"stdout_log": output.summary.stdout_log.model_dump(mode="json")},
            )
        if top_ranked_path is None:
            raise ParseError(
                "AlphaFold 3 completed but its official root-level top-ranked model "
                "(<job>_model.cif/.mmcif/.pdb) was not found; sample structures are not "
                "accepted as a substitute.",
                details={"job_name": request.job_name},
            )
        top_ranked = self.store.ref(
            top_ranked_path,
            description="AlphaFold 3 official top-ranked structure",
        )
        scores = self._confidence_scores(confidence_paths)
        input_ref = self.store.ref(input_path, media_type="application/json")
        artifacts: list[ArtifactRef] = [input_ref, *structures, *confidence_refs]
        return AlphaFold3Result(
            run_id=workspace.run_id,
            status=RunStatus.SUCCESS,
            engine="AlphaFold 3 official local runner",
            artifacts=artifacts,
            command=output.summary,
            provenance={
                "dialect": "alphafold3",
                "version": 1,
                "job_name": request.job_name,
                "model_seeds": request.seeds,
                "fallback_used": False,
            },
            input_json=input_ref,
            top_ranked_structure=top_ranked,
            structure_artifacts=structures,
            confidence_artifacts=confidence_refs,
            confidence_scores=scores,
        )

    def _refs(self, directory: Path, suffixes: set[str]) -> list[ArtifactRef]:
        return [
            self.store.ref(path, description="AlphaFold 3 predicted structure")
            for path in sorted(directory.rglob("*"))
            if path.is_file() and path.suffix.lower() in suffixes
        ]

    @staticmethod
    def _confidence_scores(paths: list[Path]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            for key, value in payload.items():
                normalized = key.lower()
                if isinstance(value, (int, float)) and any(
                    token in normalized
                    for token in ("confidence", "score", "ptm", "iptm", "ranking")
                ):
                    scores[f"{path.name}:{key}"] = float(value)
        return scores
