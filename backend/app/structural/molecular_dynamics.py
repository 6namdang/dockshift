"""Safe staged GROMACS runner for scientist-prepared systems."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.structural.artifacts import ArtifactStore
from app.structural.errors import ArtifactError, StructuralError
from app.structural.execution import LocalExecutionBackend
from app.structural.models import (
    ArtifactRef,
    GromacsRequest,
    GromacsResult,
    GromacsStageResult,
    RunStatus,
)

_COORDINATE_SUFFIXES = {".gro", ".pdb", ".g96", ".brk", ".ent"}


def validated_coordinate_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in _COORDINATE_SUFFIXES:
        allowed = ", ".join(sorted(_COORDINATE_SUFFIXES))
        raise ArtifactError(
            f"GROMACS coordinate input requires one of these file suffixes: {allowed}."
        )
    return suffix


class GromacsAdapter:
    def __init__(
        self, settings: Settings, store: ArtifactStore, backend: LocalExecutionBackend
    ) -> None:
        self.settings = settings
        self.store = store
        self.backend = backend

    async def run(self, request: GromacsRequest) -> GromacsResult:
        coordinate_source = self.store.resolve_input(request.system.coordinate.path)
        coordinate_suffix = validated_coordinate_suffix(coordinate_source)
        workspace = self.store.create_run("gromacs")
        coordinate = self.store.copy_input(
            coordinate_source,
            workspace.path,
            name=f"system{coordinate_suffix}",
        )
        topology = self._copy(request.system.topology.path, workspace.path, "topol.top")
        index = (
            self._copy(request.system.index.path, workspace.path, "index.ndx")
            if request.system.index
            else None
        )
        used_destinations = {coordinate.name, topology.name}
        if index:
            used_destinations.add(index.name)
        for include in request.system.includes:
            destination = include.destination
            if destination in used_destinations:
                raise ArtifactError(f"Duplicate GROMACS bundle destination: {destination}")
            used_destinations.add(destination)
            source = self.store.resolve_input(include.source.path)
            self.store.copy_input_relative(source, workspace.path, destination)
        mdp_paths = {
            name: self._copy(getattr(request.mdp, name).path, workspace.path, f"{name}.mdp")
            for name in ("em", "nvt", "npt", "md")
        }
        stages: list[GromacsStageResult] = []
        artifacts: list[ArtifactRef] = []
        previous_coordinate = coordinate
        previous_checkpoint: Path | None = None
        for name in ("em", "nvt", "npt", "md"):
            try:
                stage, previous_coordinate, previous_checkpoint = await self._run_stage(
                    name,
                    mdp_paths[name],
                    previous_coordinate,
                    previous_checkpoint,
                    topology,
                    index,
                    request,
                    workspace,
                )
            except StructuralError as exc:
                stages.append(
                    GromacsStageResult(
                        stage=name,
                        status=RunStatus.FAILED,
                        error=exc.message,
                        failure_details=exc.details,
                    )
                )
                status = RunStatus.PARTIAL if len(stages) > 1 else RunStatus.FAILED
                return GromacsResult(
                    run_id=workspace.run_id,
                    status=status,
                    engine="GROMACS",
                    artifacts=artifacts,
                    warnings=[
                        (
                            "The staged run stopped at the first failed stage; "
                            "inspect its command logs."
                        ),
                        "Energy and convergence analysis is a downstream scientist-reviewed step.",
                    ],
                    provenance=self._provenance(request),
                    stages=stages,
                )
            stages.append(stage)
            for candidate in (
                stage.tpr,
                stage.coordinate,
                stage.trajectory,
                stage.checkpoint,
                stage.energy,
                stage.log,
            ):
                if candidate:
                    artifacts.append(candidate)
        return GromacsResult(
            run_id=workspace.run_id,
            status=RunStatus.SUCCESS,
            engine="GROMACS",
            artifacts=artifacts,
            warnings=[
                "Completion confirms command execution only.",
                "Energy and convergence analysis is a downstream scientist-reviewed step; "
                "this runner does not report derived energy metrics.",
            ],
            provenance=self._provenance(request),
            stages=stages,
        )

    def _copy(self, reference: str, destination: Path, name: str) -> Path:
        return self.store.copy_input(self.store.resolve_input(reference), destination, name=name)

    @staticmethod
    def _is_file(path: Path) -> bool:
        return path.is_file()

    async def _run_stage(
        self,
        name: str,
        mdp: Path,
        coordinate: Path,
        checkpoint: Path | None,
        topology: Path,
        index: Path | None,
        request: GromacsRequest,
        workspace,
    ) -> tuple[GromacsStageResult, Path, Path | None]:
        tpr = workspace.path / f"{name}.tpr"
        grompp_arguments = [
            "grompp",
            "-f",
            str(mdp),
            "-c",
            str(coordinate),
            "-p",
            str(topology),
            "-o",
            str(tpr),
            "-maxwarn",
            str(request.maxwarn),
        ]
        if index:
            grompp_arguments.extend(["-n", str(index)])
        if checkpoint and self._is_file(checkpoint):
            grompp_arguments.extend(["-t", str(checkpoint)])
        grompp = await self.backend.run(
            self.settings.gromacs_executable,
            grompp_arguments,
            workspace,
            label=f"GROMACS-{name}-grompp",
        )
        mdrun_arguments = ["mdrun", "-s", str(tpr), "-deffnm", name]
        if request.threads:
            mdrun_arguments.extend(["-nt", str(request.threads)])
        mdrun = await self.backend.run(
            self.settings.gromacs_executable,
            mdrun_arguments,
            workspace,
            label=f"GROMACS-{name}-mdrun",
        )
        output_coordinate = workspace.path / f"{name}.gro"
        if not output_coordinate.is_file():
            raise ArtifactError(f"GROMACS stage {name} did not produce {name}.gro.")
        checkpoint_out = workspace.path / f"{name}.cpt"
        trajectory_path = next(
            (
                path
                for path in (workspace.path / f"{name}.xtc", workspace.path / f"{name}.trr")
                if path.is_file()
            ),
            None,
        )
        energy_path = workspace.path / f"{name}.edr"
        log_path = workspace.path / f"{name}.log"
        return (
            GromacsStageResult(
                stage=name,
                status=RunStatus.SUCCESS,
                tpr=self.store.ref(tpr, description="GROMACS portable run input"),
                coordinate=self.store.ref(output_coordinate, description="Stage-final coordinates"),
                trajectory=(
                    self.store.ref(trajectory_path, description="Trajectory")
                    if trajectory_path
                    else None
                ),
                checkpoint=(
                    self.store.ref(checkpoint_out, description="GROMACS checkpoint")
                    if checkpoint_out.is_file()
                    else None
                ),
                energy=(
                    self.store.ref(energy_path, description="GROMACS energy file")
                    if energy_path.is_file()
                    else None
                ),
                log=(
                    self.store.ref(log_path, media_type="text/plain")
                    if log_path.is_file()
                    else None
                ),
                commands=[grompp.summary, mdrun.summary],
            ),
            output_coordinate,
            checkpoint_out if checkpoint_out.is_file() else None,
        )

    @staticmethod
    def _provenance(request: GromacsRequest) -> dict:
        return {
            "stages": ["em", "nvt", "npt", "md"],
            "maxwarn": request.maxwarn,
            "threads": request.threads,
            "system_prepared_externally": True,
            "automatic_ligand_parameterization": False,
            "resume_supported": False,
            "analysis_required": "downstream scientist review of energy and convergence",
        }
