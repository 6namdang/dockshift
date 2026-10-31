"""fpocket integration and deterministic pocket geometry utilities."""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from app.config import Settings
from app.structural.artifacts import ArtifactStore, RunWorkspace
from app.structural.errors import GeometryError, ParseError
from app.structural.execution import LocalExecutionBackend
from app.structural.models import (
    DockingBox,
    FPocketRequest,
    FPocketResult,
    Pocket,
    PocketBoxRequest,
    PocketComparisonRequest,
    PocketComparisonResult,
    RunStatus,
    Vector3,
)

_POCKET_HEADER = re.compile(r"Pocket\s+(\d+)\s*:?", re.IGNORECASE)
_VALUE = re.compile(r"^\s*([^:]+?)\s*:\s*([-+\d.eE]+)\s*$")
_POCKET_FILE_ID = re.compile(r"pocket(\d+)", re.IGNORECASE)


def _vector(values: np.ndarray) -> Vector3:
    return Vector3(x=float(values[0]), y=float(values[1]), z=float(values[2]))


def _parse_info(path: Path | None) -> dict[int, dict[str, float]]:
    if path is None:
        return {}
    result: dict[int, dict[str, float]] = {}
    current: int | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        header = _POCKET_HEADER.search(line)
        if header:
            current = int(header.group(1))
            result.setdefault(current, {})
            continue
        value = _VALUE.match(line)
        if current is None or value is None:
            continue
        key = " ".join(value.group(1).lower().split())
        result[current][key] = float(value.group(2))
    return result


def _pdb_atoms(path: Path) -> tuple[np.ndarray, list[str]]:
    coordinates: list[list[float]] = []
    residues: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54:
            continue
        try:
            coordinates.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        except ValueError:
            continue
        residue = line[17:20].strip()
        chain = line[21:22].strip() or "_"
        number = line[22:26].strip()
        insertion = line[26:27].strip()
        # fpocket alpha spheres use STP; do not report them as protein residues.
        if residue and residue.upper() != "STP":
            residues.add(f"{chain}:{residue}:{number}{insertion}")
    if not coordinates:
        raise ParseError(
            "fpocket pocket file contained no parseable atom coordinates.",
            details={"artifact": path.name},
        )
    return np.asarray(coordinates, dtype=float), sorted(residues)


def parse_fpocket_outputs(output_dir: Path, store: ArtifactStore) -> tuple[list[Pocket], list]:
    info_path = next(iter(sorted(output_dir.glob("*_info.txt"))), None)
    info = _parse_info(info_path)
    pocket_files = sorted((output_dir / "pockets").glob("pocket*_atm.pdb"))
    pockets: list[Pocket] = []
    artifacts = []
    if info_path:
        artifacts.append(
            store.ref(info_path, media_type="text/plain", description="fpocket scores")
        )
    for path in pocket_files:
        match = _POCKET_FILE_ID.search(path.name)
        if not match:
            continue
        pocket_id = int(match.group(1))
        coordinates, residues = _pdb_atoms(path)
        values = info.get(pocket_id, {})
        artifact = store.ref(path, media_type="chemical/x-pdb", description="fpocket atoms")
        artifacts.append(artifact)
        score = next((value for key, value in values.items() if key == "score"), None)
        druggability = next(
            (value for key, value in values.items() if "druggability score" in key), None
        )
        volume = next((value for key, value in values.items() if "volume" in key), None)
        pockets.append(
            Pocket(
                pocket_id=pocket_id,
                center=_vector(coordinates.mean(axis=0)),
                minimum=_vector(coordinates.min(axis=0)),
                maximum=_vector(coordinates.max(axis=0)),
                atom_coordinates=[_vector(row) for row in coordinates],
                residue_ids=residues,
                score=score,
                druggability_score=druggability,
                volume_angstrom3=volume if volume is None or volume >= 0 else None,
                artifact=artifact,
            )
        )
    return pockets, artifacts


def _coordinates(pocket: Pocket) -> np.ndarray:
    return np.asarray([point.values() for point in pocket.atom_coordinates], dtype=float)


def _overlap_fraction(source: np.ndarray, target: np.ndarray, threshold: float) -> float:
    """Return the fraction with a neighbor at or within the inclusive threshold."""
    if source.size == 0 or target.size == 0:
        return 0.0
    inclusive_threshold = float(np.nextafter(threshold, math.inf))
    distances, _ = cKDTree(target).query(
        source,
        k=1,
        distance_upper_bound=inclusive_threshold,
        workers=1,
    )
    return float(np.count_nonzero(np.isfinite(distances)) / len(source))


def compare_pockets(request: PocketComparisonRequest) -> PocketComparisonResult:
    rotation = np.asarray(request.moving_to_reference.rotation, dtype=float)
    translation = np.asarray(request.moving_to_reference.translation, dtype=float)
    moving = _coordinates(request.moving_pocket)
    reference = _coordinates(request.reference_pocket)
    transformed = moving @ rotation.T + translation
    moving_center = np.asarray(request.moving_pocket.center.values(), dtype=float)
    reference_center = np.asarray(request.reference_pocket.center.values(), dtype=float)
    transformed_center = rotation @ moving_center + translation
    center_distance = float(np.linalg.norm(transformed_center - reference_center))
    forward = _overlap_fraction(transformed, reference, request.overlap_threshold_angstrom)
    reverse = _overlap_fraction(reference, transformed, request.overlap_threshold_angstrom)
    overlap = (forward + reverse) / 2
    moving_size = max(len(moving), 1)
    reference_size = max(len(reference), 1)
    size_ratio = min(moving_size, reference_size) / max(moving_size, reference_size)
    moving_volume = request.moving_pocket.volume_angstrom3
    reference_volume = request.reference_pocket.volume_angstrom3
    volume_ratio = None
    if (
        moving_volume is not None
        and reference_volume is not None
        and max(moving_volume, reference_volume) > 0
    ):
        volume_ratio = min(moving_volume, reference_volume) / max(moving_volume, reference_volume)
    scale_ratio = volume_ratio if volume_ratio is not None else size_ratio
    center_similarity = math.exp(-center_distance / 5.0)
    composite = 0.35 * center_similarity + 0.45 * overlap + 0.20 * scale_ratio
    return PocketComparisonResult(
        transformed_centroid_distance_angstrom=round(center_distance, 4),
        nearest_neighbor_overlap=round(overlap, 4),
        size_ratio=round(size_ratio, 4),
        volume_ratio=round(volume_ratio, 4) if volume_ratio is not None else None,
        composite_similarity=round(float(composite), 4),
        formula=(
            "0.35*exp(-centroid_distance/5Å) + 0.45*symmetric atom-overlap + "
            "0.20*(volume ratio when available, otherwise atom-count ratio)"
        ),
        warning=(
            "This deterministic geometry score compares pocket shape after rigid-body "
            "superposition. It does not establish biological or pharmacological equivalence."
        ),
    )


def docking_box_from_pocket(request: PocketBoxRequest) -> DockingBox:
    minimum = np.asarray(request.pocket.minimum.values(), dtype=float)
    maximum = np.asarray(request.pocket.maximum.values(), dtype=float)
    center = (minimum + maximum) / 2
    size = np.maximum(maximum - minimum + 2 * request.padding_angstrom, 1.0)
    if np.any(size > request.max_size_angstrom):
        dimensions = ", ".join(f"{value:.2f}" for value in size)
        raise GeometryError(
            "Pocket bounds plus padding produce an oversized docking box "
            f"({dimensions} Å; maximum {request.max_size_angstrom:.2f} Å per axis). "
            "Supply explicit scientist-reviewed box coordinates instead of clipping."
        )
    return DockingBox(center=_vector(center), size=_vector(size))


class FPocketAdapter:
    def __init__(
        self, settings: Settings, store: ArtifactStore, backend: LocalExecutionBackend
    ) -> None:
        self.settings = settings
        self.store = store
        self.backend = backend

    async def run(self, request: FPocketRequest) -> FPocketResult:
        workspace = self.store.create_run("fpocket")
        source = self.store.resolve_input(request.structure.path)
        local = await self._local_pdb(source, workspace)
        output = await self.backend.run(
            self.settings.fpocket_executable,
            ["-f", str(local)],
            workspace,
            label="fpocket",
        )
        output_dir = workspace.path / f"{local.stem}_out"
        if not output_dir.is_dir():
            candidates = sorted(workspace.path.glob("*_out"))
            output_dir = candidates[0] if candidates else output_dir
        if not output_dir.is_dir():
            raise ParseError(
                "fpocket completed but its output directory was not found.",
                details={"stdout_log": output.summary.stdout_log.model_dump(mode="json")},
            )
        pockets, artifacts = parse_fpocket_outputs(output_dir, self.store)
        if not pockets:
            raise ParseError("fpocket completed but no pocket atom files were discovered.")
        version = next(
            (line.strip() for line in output.stdout.splitlines() if "fpocket" in line.lower()),
            None,
        )
        return FPocketResult(
            run_id=workspace.run_id,
            status=RunStatus.SUCCESS,
            engine="fpocket",
            engine_version=version,
            artifacts=artifacts,
            command=output.summary,
            provenance={"structure": request.structure.path},
            pockets=pockets,
        )

    async def _local_pdb(self, source: Path, workspace: RunWorkspace) -> Path:
        if source.suffix.lower() in {".pdb", ".ent"}:
            return self.store.copy_input(source, workspace.path, name="protein.pdb")
        local = workspace.path / "protein.pdb"
        await self.backend.run(
            self.settings.obabel_executable,
            [str(source), "-O", str(local)],
            workspace,
            label="Open-Babel-fpocket-conversion",
        )
        if not local.is_file():
            raise ParseError("Open Babel did not create the PDB required by fpocket.")
        return local
