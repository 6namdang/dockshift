"""AutoDock Vina adapter."""

from __future__ import annotations

import math
import re
from pathlib import Path

from app.config import Settings
from app.structural.artifacts import ArtifactStore
from app.structural.errors import ParseError
from app.structural.execution import LocalExecutionBackend
from app.structural.models import DockingMode, DockingRequest, DockingResult, RunStatus

_MODE_RE = re.compile(
    r"^\s*(\d+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s*$",
    re.MULTILINE,
)
_POSE_RE = re.compile(
    r"REMARK\s+VINA\s+RESULT:\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)",
    re.IGNORECASE,
)


def parse_vina_modes(text: str) -> list[DockingMode]:
    modes = [
        DockingMode(
            rank=int(match.group(1)),
            affinity_kcal_mol=float(match.group(2)),
            rmsd_lower_bound_angstrom=float(match.group(3)),
            rmsd_upper_bound_angstrom=float(match.group(4)),
        )
        for match in _MODE_RE.finditer(text)
    ]
    return sorted(modes, key=lambda mode: mode.rank)


def _pose_blocks(text: str) -> list[list[str]]:
    lines = text.splitlines()
    has_models = any(line.startswith("MODEL") for line in lines)
    if not has_models:
        return [lines]
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("MODEL"):
            if current is not None:
                raise ParseError("Vina pose file contains nested or unterminated MODEL records.")
            current = []
        elif line.startswith("ENDMDL"):
            if current is None:
                raise ParseError("Vina pose file contains ENDMDL without MODEL.")
            blocks.append(current)
            current = None
        elif current is not None:
            current.append(line)
    if current is not None:
        raise ParseError("Vina pose file contains an unterminated MODEL record.")
    return blocks


def _has_parseable_atom(lines: list[str]) -> bool:
    for line in lines:
        if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54:
            continue
        try:
            float(line[30:38])
            float(line[38:46])
            float(line[46:54])
        except ValueError:
            continue
        return True
    return False


def validate_vina_pose(path: Path, table_modes: list[DockingMode]) -> list[DockingMode]:
    """Require parseable atom-bearing pose models consistent with Vina's ranked table."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ParseError("AutoDock Vina did not create a non-empty pose file.")
    text = path.read_text(encoding="utf-8", errors="replace")
    pose_modes: list[DockingMode] = []
    for rank, block in enumerate(_pose_blocks(text), start=1):
        if not _has_parseable_atom(block):
            raise ParseError(f"Vina pose model {rank} contains no parseable ATOM/HETATM records.")
        matches = list(_POSE_RE.finditer("\n".join(block)))
        if len(matches) != 1:
            raise ParseError(
                f"Vina pose model {rank} must contain exactly one parseable VINA RESULT record."
            )
        match = matches[0]
        try:
            pose_modes.append(
                DockingMode(
                    rank=rank,
                    affinity_kcal_mol=float(match.group(1)),
                    rmsd_lower_bound_angstrom=float(match.group(2)),
                    rmsd_upper_bound_angstrom=float(match.group(3)),
                )
            )
        except ValueError as exc:
            raise ParseError(f"Vina pose model {rank} contains invalid numeric scores.") from exc
    if not pose_modes:
        raise ParseError("AutoDock Vina pose file contains no pose models.")
    if table_modes:
        if [mode.rank for mode in table_modes] != list(range(1, len(table_modes) + 1)):
            raise ParseError("AutoDock Vina ranked table has duplicate or non-consecutive ranks.")
        if len(table_modes) != len(pose_modes):
            raise ParseError("AutoDock Vina ranked-table and pose-model counts are inconsistent.")
        for table, pose in zip(table_modes, pose_modes, strict=True):
            values = (
                (table.affinity_kcal_mol, pose.affinity_kcal_mol),
                (table.rmsd_lower_bound_angstrom, pose.rmsd_lower_bound_angstrom),
                (table.rmsd_upper_bound_angstrom, pose.rmsd_upper_bound_angstrom),
            )
            if any(
                left is None or right is None or not math.isclose(left, right, abs_tol=1e-3)
                for left, right in values
            ):
                raise ParseError(
                    f"AutoDock Vina ranked table disagrees with pose model {pose.rank}."
                )
        return table_modes
    return pose_modes


class VinaAdapter:
    def __init__(
        self, settings: Settings, store: ArtifactStore, backend: LocalExecutionBackend
    ) -> None:
        self.settings = settings
        self.store = store
        self.backend = backend

    async def dock(self, request: DockingRequest) -> DockingResult:
        workspace = self.store.create_run("vina")
        receptor_source = self.store.resolve_input(request.receptor_pdbqt.path)
        ligand_source = self.store.resolve_input(request.ligand_pdbqt.path)
        receptor = self.store.copy_input(receptor_source, workspace.path, name="receptor.pdbqt")
        ligand = self.store.copy_input(ligand_source, workspace.path, name="ligand.pdbqt")
        pose_path = workspace.path / "poses.pdbqt"
        arguments = [
            "--receptor",
            str(receptor),
            "--ligand",
            str(ligand),
            "--center_x",
            str(request.box.center.x),
            "--center_y",
            str(request.box.center.y),
            "--center_z",
            str(request.box.center.z),
            "--size_x",
            str(request.box.size.x),
            "--size_y",
            str(request.box.size.y),
            "--size_z",
            str(request.box.size.z),
            "--exhaustiveness",
            str(request.exhaustiveness),
            "--num_modes",
            str(request.num_modes),
            "--energy_range",
            str(request.energy_range),
            "--out",
            str(pose_path),
        ]
        if request.seed is not None:
            arguments.extend(["--seed", str(request.seed)])
        output = await self.backend.run(
            self.settings.vina_executable,
            arguments,
            workspace,
            label="AutoDock-Vina",
        )
        table_modes = parse_vina_modes(f"{output.stdout}\n{output.stderr}")
        modes = validate_vina_pose(pose_path, table_modes)
        pose_ref = self.store.ref(
            pose_path, media_type="chemical/x-pdbqt", description="Ranked Vina poses"
        )
        version = next(
            (line.strip() for line in output.stdout.splitlines() if "vina" in line.lower()),
            None,
        )
        return DockingResult(
            run_id=workspace.run_id,
            status=RunStatus.SUCCESS,
            engine="AutoDock Vina",
            engine_version=version,
            artifacts=[pose_ref],
            command=output.summary,
            provenance={
                "receptor": request.receptor_pdbqt.path,
                "ligand": request.ligand_pdbqt.path,
                "box": request.box.model_dump(mode="json"),
                "exhaustiveness": request.exhaustiveness,
                "num_modes": request.num_modes,
                "energy_range_kcal_mol": request.energy_range,
                "seed": request.seed,
            },
            modes=modes,
            pose=pose_ref,
            md_ready=False,
            md_prerequisites=[
                "Scientist-approved ligand force-field parameters and charges",
                "A solvated, neutralized protein-ligand GROMACS topology/coordinate bundle",
                "Reviewed restraints, protonation states, cofactors, and simulation protocol",
            ],
            warnings=[
                "Vina affinity is a docking score, not an experimental binding free energy.",
                "Docking poses are not directly suitable as a GROMACS system.",
            ],
        )
