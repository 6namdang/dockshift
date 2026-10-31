"""Facade shared by structural REST routes and MCP tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import BACKEND_DIR, Settings, get_settings
from app.structural.admission import (
    StructuralAdmissionController,
    get_structural_admission_controller,
)
from app.structural.alphafold3 import AlphaFold3Adapter
from app.structural.artifacts import ArtifactStore
from app.structural.docking import VinaAdapter
from app.structural.execution import LocalExecutionBackend, probe_version
from app.structural.models import (
    AlphaFold3Request,
    AlphaFold3Result,
    CapabilitiesResult,
    DockingBox,
    DockingRequest,
    DockingResult,
    FPocketRequest,
    FPocketResult,
    GromacsRequest,
    GromacsResult,
    LigandPreparationRequest,
    LigandPreparationResult,
    PocketBoxRequest,
    PocketComparisonRequest,
    PocketComparisonResult,
    PocketPlanRequest,
    PocketPlanResult,
    ReceptorPreparationRequest,
    ReceptorPreparationResult,
    RunStatus,
    StructuralWorkflowRequest,
    StructuralWorkflowResult,
    TMAlignRequest,
    TMAlignResult,
    ToolCapability,
)
from app.structural.molecular_dynamics import GromacsAdapter
from app.structural.planning import PocketPlanStore
from app.structural.pockets import FPocketAdapter, compare_pockets, docking_box_from_pocket
from app.structural.preparation import PreparationService
from app.structural.tmalign import TMAlignAdapter
from app.structural.workflow import StructuralWorkflow


class StructuralService:
    def __init__(
        self,
        settings: Settings | None = None,
        admission: StructuralAdmissionController | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.admission_controller = admission or get_structural_admission_controller(
            self.settings.structural_max_concurrent_jobs
        )
        self.store = ArtifactStore(self.settings)
        self.backend = LocalExecutionBackend(
            self.store,
            self.settings.structural_command_timeout_seconds,
            self.settings.structural_log_max_bytes,
        )
        self.alphafold3_adapter = AlphaFold3Adapter(self.settings, self.store, self.backend)
        self.tmalign_adapter = TMAlignAdapter(self.settings, self.store, self.backend)
        self.fpocket_adapter = FPocketAdapter(self.settings, self.store, self.backend)
        self.preparation = PreparationService(self.settings, self.store, self.backend)
        self.vina_adapter = VinaAdapter(self.settings, self.store, self.backend)
        self.gromacs_adapter = GromacsAdapter(self.settings, self.store, self.backend)
        self.pocket_plans = PocketPlanStore(self.store)
        self.workflow = StructuralWorkflow(
            self.store,
            self._capabilities_unlocked,
            self.pocket_plans,
            self.preparation,
            self.vina_adapter,
        )

    async def capabilities(self) -> CapabilitiesResult:
        async with self.admission_controller.admit():
            return await self._capabilities_unlocked()

    async def _capabilities_unlocked(self) -> CapabilitiesResult:
        specs = [
            ("TM-align", self.settings.tmalign_executable, ["-h"]),
            ("fpocket", self.settings.fpocket_executable, ["-v"]),
            ("AutoDock Vina", self.settings.vina_executable, ["--version"]),
            ("Open Babel", self.settings.obabel_executable, ["-V"]),
            ("GROMACS", self.settings.gromacs_executable, ["--version"]),
        ]
        probes = await asyncio.gather(
            *(probe_version(executable, arguments) for _, executable, arguments in specs)
        )
        capabilities = [
            ToolCapability(
                tool=name,
                configured_value=Path(executable).name,
                available=resolved is not None,
                resolved_executable=Path(resolved).name if resolved else None,
                version=version,
                reason=None
                if resolved
                else "Configured executable was not found or is not executable.",
            )
            for (name, executable, _), (resolved, version) in zip(specs, probes, strict=True)
        ]
        script = self._config_path(self.settings.alphafold3_script)
        model_dir = self._config_path(self.settings.alphafold3_model_dir)
        database_dir = self._config_path(self.settings.alphafold3_database_dir)
        python_resolved, python_version = await probe_version(
            self.settings.alphafold3_python_executable, ["--version"]
        )
        missing = []
        if python_resolved is None:
            missing.append("ALPHAFOLD3_PYTHON_EXECUTABLE")
        if script is None or not script.is_file():
            missing.append("ALPHAFOLD3_SCRIPT")
        if model_dir is None or not model_dir.is_dir():
            missing.append("ALPHAFOLD3_MODEL_DIR")
        if database_dir is None or not database_dir.is_dir():
            missing.append("ALPHAFOLD3_DATABASE_DIR")
        capabilities.append(
            ToolCapability(
                tool="AlphaFold 3",
                configured_value=None,
                available=not missing,
                resolved_executable=Path(python_resolved).name if python_resolved else None,
                version=f"runner {python_version}" if python_version else None,
                reason=f"Missing or invalid: {', '.join(missing)}" if missing else None,
            )
        )
        available = sum(capability.available for capability in capabilities)
        return CapabilitiesResult(
            status=RunStatus.SUCCESS if available == len(capabilities) else RunStatus.PARTIAL,
            artifact_root="managed; host path is not disclosed",
            tools=capabilities,
            notes=[
                "External scientific engines and AlphaFold 3 assets are not bundled.",
                "Remote execution is not implemented; this service runs configured local tools.",
            ],
        )

    @staticmethod
    def _config_path(value: Path | None) -> Path | None:
        if value is None:
            return None
        return (value if value.is_absolute() else BACKEND_DIR / value).expanduser().resolve()

    async def tmalign(self, request: TMAlignRequest) -> TMAlignResult:
        async with self.admission_controller.admit():
            return await self.tmalign_adapter.align(request)

    async def alphafold3(self, request: AlphaFold3Request) -> AlphaFold3Result:
        async with self.admission_controller.admit():
            return await self.alphafold3_adapter.run(request)

    async def prepare_ligand(self, request: LigandPreparationRequest) -> LigandPreparationResult:
        async with self.admission_controller.admit():
            return await self.preparation.prepare_ligand(request)

    async def prepare_receptor(
        self, request: ReceptorPreparationRequest
    ) -> ReceptorPreparationResult:
        async with self.admission_controller.admit():
            return await self.preparation.prepare_receptor(request)

    async def fpocket(self, request: FPocketRequest) -> FPocketResult:
        async with self.admission_controller.admit():
            return await self.fpocket_adapter.run(request)

    async def compare_pockets(self, request: PocketComparisonRequest) -> PocketComparisonResult:
        async with self.admission_controller.admit():
            return await asyncio.to_thread(compare_pockets, request)

    async def pocket_box(self, request: PocketBoxRequest) -> DockingBox:
        async with self.admission_controller.admit():
            return await asyncio.to_thread(docking_box_from_pocket, request)

    async def create_pocket_plan(self, request: PocketPlanRequest) -> PocketPlanResult:
        async with self.admission_controller.admit():
            return await asyncio.to_thread(self.pocket_plans.create, request)

    async def dock(self, request: DockingRequest) -> DockingResult:
        async with self.admission_controller.admit():
            return await self.vina_adapter.dock(request)

    async def run_gromacs(self, request: GromacsRequest) -> GromacsResult:
        async with self.admission_controller.admit():
            return await self.gromacs_adapter.run(request)

    async def run_workflow(self, request: StructuralWorkflowRequest) -> StructuralWorkflowResult:
        async with self.admission_controller.admit():
            return await self.workflow.run(request)
