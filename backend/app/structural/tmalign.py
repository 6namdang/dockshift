"""TM-align adapter and tolerant output parser."""

from __future__ import annotations

import re

from app.config import Settings
from app.structural.artifacts import ArtifactStore
from app.structural.errors import ParseError
from app.structural.execution import LocalExecutionBackend
from app.structural.models import RigidTransform, RunStatus, TMAlignRequest, TMAlignResult

_ALIGNED_RE = re.compile(
    r"Aligned\s+length\s*=\s*(\d+)\s*,\s*RMSD\s*=\s*([-+\d.eE]+)\s*,.*?=\s*([-+\d.eE]+)",
    re.IGNORECASE,
)
_TM_RE = re.compile(r"TM-score\s*=\s*([-+\d.eE]+)", re.IGNORECASE)
_FLOAT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def parse_tmalign_output(stdout: str, matrix_text: str | None = None) -> dict[str, object]:
    metrics: dict[str, object] = {}
    aligned = _ALIGNED_RE.search(stdout)
    if aligned:
        metrics.update(
            aligned_length=int(aligned.group(1)),
            rmsd_angstrom=float(aligned.group(2)),
            sequence_identity=float(aligned.group(3)),
        )
    scores = [float(value) for value in _TM_RE.findall(stdout)]
    if scores:
        metrics["tm_score_structure_a"] = scores[0]
    if len(scores) > 1:
        metrics["tm_score_structure_b"] = scores[1]
    if matrix_text:
        transform = parse_transform_matrix(matrix_text)
        if transform:
            metrics["transform_a_to_b"] = transform
    return metrics


def parse_transform_matrix(text: str) -> RigidTransform | None:
    indexed_rows: dict[int, list[float]] = {}
    unindexed_rows: list[list[float]] = []
    started = False
    for line in text.splitlines():
        if "rotation matrix" in line.lower():
            started = True
            continue
        if not started:
            continue
        values = [float(value) for value in _FLOAT_RE.findall(line)]
        # Official TM-align -m output uses rows 1, 2, 3. Retain support for
        # wrappers that emit equivalent zero-based or unindexed four-value rows.
        if len(values) >= 5 and values[0].is_integer():
            indexed_rows[int(values[0])] = values[-4:]
        elif len(values) == 4:
            unindexed_rows.append(values)

    rows: list[list[float]] | None = None
    if all(index in indexed_rows for index in (1, 2, 3)):
        rows = [indexed_rows[index] for index in (1, 2, 3)]
    elif all(index in indexed_rows for index in (0, 1, 2)):
        rows = [indexed_rows[index] for index in (0, 1, 2)]
    elif len(unindexed_rows) >= 3:
        rows = unindexed_rows[:3]
    if rows is None:
        return None
    return RigidTransform(
        translation=[row[0] for row in rows],
        rotation=[row[1:] for row in rows],
    )


class TMAlignAdapter:
    def __init__(
        self, settings: Settings, store: ArtifactStore, backend: LocalExecutionBackend
    ) -> None:
        self.settings = settings
        self.store = store
        self.backend = backend

    async def align(self, request: TMAlignRequest) -> TMAlignResult:
        workspace = self.store.create_run("tmalign")
        structure_a = self.store.resolve_input(request.structure_a.path)
        structure_b = self.store.resolve_input(request.structure_b.path)
        local_a = self.store.copy_input(
            structure_a, workspace.path, name=f"structure_a{structure_a.suffix}"
        )
        local_b = self.store.copy_input(
            structure_b, workspace.path, name=f"structure_b{structure_b.suffix}"
        )
        matrix_path = workspace.path / "transform.txt"
        superposition_prefix = workspace.path / "superposition"
        output = await self.backend.run(
            self.settings.tmalign_executable,
            [
                str(local_a),
                str(local_b),
                "-m",
                str(matrix_path),
                "-o",
                str(superposition_prefix),
            ],
            workspace,
            label="TM-align",
        )
        matrix_text = (
            matrix_path.read_text(encoding="utf-8", errors="replace")
            if matrix_path.is_file()
            else None
        )
        metrics = parse_tmalign_output(output.stdout, matrix_text)
        if not {"aligned_length", "rmsd_angstrom"}.issubset(metrics):
            raise ParseError(
                "TM-align completed but its alignment metrics could not be parsed.",
                details={"stdout_log": output.summary.stdout_log.model_dump(mode="json")},
            )
        artifacts = []
        if matrix_path.is_file():
            artifacts.append(
                self.store.ref(
                    matrix_path, media_type="text/plain", description="TM-align transform matrix"
                )
            )
        for path in sorted(workspace.path.glob("superposition*")):
            if path.is_file():
                artifacts.append(self.store.ref(path, description="TM-align superposition output"))
        version = next(
            (line.strip() for line in output.stdout.splitlines() if "TM-align" in line), None
        )
        return TMAlignResult(
            run_id=workspace.run_id,
            status=RunStatus.SUCCESS,
            engine="TM-align",
            engine_version=version,
            artifacts=artifacts,
            command=output.summary,
            provenance={
                "structure_a": request.structure_a.path,
                "structure_b": request.structure_b.path,
                "transform_direction": "structure_a_to_structure_b",
            },
            **metrics,
        )
