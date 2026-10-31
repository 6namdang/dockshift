"""Scientist-approved hTERT/tcTERT structural-discovery orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.structural.artifacts import ArtifactStore, RunWorkspace
from app.structural.docking import VinaAdapter
from app.structural.errors import StructuralError
from app.structural.models import (
    CandidateLigand,
    CapabilitiesResult,
    DockingBox,
    DockingRequest,
    FileInput,
    LigandPreparationRequest,
    ReceptorPreparationRequest,
    RunStatus,
    StructuralWorkflowRequest,
    StructuralWorkflowResult,
    WorkflowCandidateResult,
)
from app.structural.planning import PocketPlanStore, sha256_file
from app.structural.preparation import PreparationService

_DEFAULT_CONFORMER_SEED = 61453


def aggregate_workflow_status(candidates: list[WorkflowCandidateResult]) -> RunStatus:
    if all(item.status == RunStatus.SUCCESS for item in candidates):
        return RunStatus.SUCCESS
    if any(
        item.preparation is not None
        or item.tctert_docking is not None
        or item.htert_docking is not None
        for item in candidates
    ):
        return RunStatus.PARTIAL
    return RunStatus.FAILED


class StructuralWorkflow:
    def __init__(
        self,
        store: ArtifactStore,
        capabilities: Callable[[], Awaitable[CapabilitiesResult]],
        pocket_plans: PocketPlanStore,
        preparation: PreparationService,
        vina: VinaAdapter,
    ) -> None:
        self.store = store
        self.capabilities = capabilities
        self.pocket_plans = pocket_plans
        self.preparation = preparation
        self.vina = vina

    async def run(self, request: StructuralWorkflowRequest) -> StructuralWorkflowResult:
        workspace = self.store.create_run("workflow")
        preflight = await self.capabilities()
        required = {"Open Babel", "AutoDock Vina"}
        unavailable = [
            capability.tool
            for capability in preflight.tools
            if capability.tool in required and not capability.available
        ]
        if unavailable:
            return self._failed(workspace.run_id, preflight, request, unavailable)

        # The workflow owns one admission slot. Load and hash in a worker thread, then call
        # adapters directly so no nested admission acquisition can deadlock.
        plan = await asyncio.to_thread(
            self.pocket_plans.load_verified,
            request.pocket_approval,
            request.tctert_structure,
            request.htert_structure,
        )
        tc_pocket = plan.selected_tctert_pocket
        human_pocket = plan.selected_htert_pocket
        tc_box = plan.tctert_docking_box
        human_box = plan.htert_docking_box
        tc_receptor = await self.preparation.prepare_receptor(
            ReceptorPreparationRequest(structure=request.tctert_structure)
        )
        human_receptor = await self.preparation.prepare_receptor(
            ReceptorPreparationRequest(structure=request.htert_structure)
        )

        candidates = []
        for candidate in request.candidates:
            candidates.append(
                await self._process_candidate(
                    candidate,
                    workspace,
                    tc_receptor.pdbqt.path,
                    human_receptor.pdbqt.path,
                    tc_box,
                    human_box,
                    request,
                )
            )
        ranked = sorted(
            (
                item
                for item in candidates
                if item.status == RunStatus.SUCCESS and item.best_affinity_kcal_mol is not None
            ),
            key=lambda item: (item.best_affinity_kcal_mol, item.candidate_id),
        )
        status = aggregate_workflow_status(candidates)
        conformer_seed = (
            request.docking_seed if request.docking_seed is not None else _DEFAULT_CONFORMER_SEED
        )
        approval = request.pocket_approval
        return StructuralWorkflowResult(
            run_id=workspace.run_id,
            status=status,
            engine="Dockshift structural workflow",
            warnings=[
                "Ranking uses the best hTERT-pocket Vina score; it is a computational "
                "triage signal, not measured affinity.",
                "MD is intentionally separate because docking outputs lack an approved "
                "solvated topology.",
            ],
            provenance={
                "candidate_count": len(request.candidates),
                "ranking_metric": "best hTERT AutoDock Vina affinity (kcal/mol), ascending",
                "pocket_approval": approval.model_dump(mode="json"),
                "tctert_structure_sha256": plan.tctert_structure_sha256,
                "htert_structure_sha256": plan.htert_structure_sha256,
                "conformer_seed": conformer_seed,
                "vina_seed": request.docking_seed,
            },
            preflight=preflight,
            pocket_plan_artifact=approval.proposal_artifact,
            pocket_plan_sha256=approval.proposal_sha256,
            approved_transform_tctert_to_htert=plan.transform_tctert_to_htert,
            selected_tctert_pocket=tc_pocket,
            selected_htert_pocket=human_pocket,
            selected_tctert_pocket_id=tc_pocket.pocket_id,
            selected_htert_pocket_id=human_pocket.pocket_id,
            pocket_comparison=plan.pocket_comparison,
            tctert_docking_box=tc_box,
            htert_docking_box=human_box,
            tctert_receptor_preparation=tc_receptor,
            htert_receptor_preparation=human_receptor,
            candidates=candidates,
            ranking=[item.candidate_id for item in ranked],
            literature_checkpoint=request.after_qsar_literature_checkpoint,
            md_next_step=self._md_next_step(),
        )

    async def _process_candidate(
        self,
        candidate: CandidateLigand,
        workspace: RunWorkspace,
        tctert_receptor: str,
        htert_receptor: str,
        tctert_box: DockingBox,
        htert_box: DockingBox,
        request: StructuralWorkflowRequest,
    ) -> WorkflowCandidateResult:
        preparation = None
        tc_docking = None
        human_docking = None
        stage = "input_identity"
        identity: dict = {
            "submitted_smiles": candidate.smiles,
            "submitted_sdf_path": candidate.sdf.path if candidate.sdf else None,
            "submitted_sdf_artifact": None,
            "submitted_sdf_sha256": None,
        }
        conformer_seed = (
            request.docking_seed if request.docking_seed is not None else _DEFAULT_CONFORMER_SEED
        )
        try:
            preparation_sdf = candidate.sdf
            if candidate.sdf is not None:
                source = self.store.resolve_input(candidate.sdf.path)
                staged = self.store.copy_input(
                    source,
                    workspace.path / "candidate-inputs",
                    name=f"{self.store.safe_name(candidate.candidate_id)}.sdf",
                )
                staged_ref = self.store.ref(
                    staged,
                    media_type="chemical/x-mdl-sdfile",
                    description="Immutable submitted workflow SDF",
                )
                identity["submitted_sdf_artifact"] = staged_ref
                identity["submitted_sdf_sha256"] = await asyncio.to_thread(sha256_file, staged)
                preparation_sdf = FileInput(path=staged_ref.path)
            stage = "ligand_preparation"
            preparation = await self.preparation.prepare_ligand(
                LigandPreparationRequest(
                    name=candidate.candidate_id,
                    smiles=candidate.smiles,
                    sdf=preparation_sdf,
                    random_seed=conformer_seed,
                )
            )
            stage = "tctert_docking"
            tc_docking = await self.vina.dock(
                DockingRequest(
                    receptor_pdbqt=FileInput(path=tctert_receptor),
                    ligand_pdbqt=FileInput(path=preparation.pdbqt.path),
                    box=tctert_box,
                    exhaustiveness=request.docking_exhaustiveness,
                    num_modes=request.docking_num_modes,
                    seed=request.docking_seed,
                )
            )
            stage = "htert_docking"
            human_docking = await self.vina.dock(
                DockingRequest(
                    receptor_pdbqt=FileInput(path=htert_receptor),
                    ligand_pdbqt=FileInput(path=preparation.pdbqt.path),
                    box=htert_box,
                    exhaustiveness=request.docking_exhaustiveness,
                    num_modes=request.docking_num_modes,
                    seed=request.docking_seed,
                )
            )
            affinity = human_docking.modes[0].affinity_kcal_mol
            return WorkflowCandidateResult(
                candidate_id=candidate.candidate_id,
                status=RunStatus.SUCCESS,
                **identity,
                preparation=preparation,
                tctert_docking=tc_docking,
                htert_docking=human_docking,
                best_affinity_kcal_mol=affinity,
                conformer_seed=conformer_seed,
                vina_seed=request.docking_seed,
                qsar_metadata=candidate.qsar_metadata,
            )
        except StructuralError as exc:
            status = (
                RunStatus.PARTIAL
                if preparation is not None or tc_docking is not None
                else RunStatus.FAILED
            )
            return WorkflowCandidateResult(
                candidate_id=candidate.candidate_id,
                status=status,
                **identity,
                preparation=preparation,
                tctert_docking=tc_docking,
                htert_docking=human_docking,
                conformer_seed=conformer_seed,
                vina_seed=request.docking_seed,
                failed_stage=stage,
                error=exc.message,
                error_details={"code": exc.code, "details": exc.details},
                qsar_metadata=candidate.qsar_metadata,
            )
        except Exception as exc:  # isolate a candidate without exposing host details
            status = (
                RunStatus.PARTIAL
                if preparation is not None or tc_docking is not None
                else RunStatus.FAILED
            )
            return WorkflowCandidateResult(
                candidate_id=candidate.candidate_id,
                status=status,
                **identity,
                preparation=preparation,
                tctert_docking=tc_docking,
                htert_docking=human_docking,
                conformer_seed=conformer_seed,
                vina_seed=request.docking_seed,
                failed_stage=stage,
                error=f"Unexpected candidate failure: {type(exc).__name__}",
                error_details={"code": "unexpected_candidate_failure"},
                qsar_metadata=candidate.qsar_metadata,
            )

    @staticmethod
    def _md_next_step() -> str:
        return (
            "Have a scientist parameterize the selected ligand and build/review a solvated "
            "GROMACS coordinate/topology bundle, then submit it with em/nvt/npt/md MDP "
            "files to /gromacs/run. Analyze energy and convergence separately after the run."
        )

    @classmethod
    def _failed(
        cls,
        run_id: str,
        preflight: CapabilitiesResult,
        request: StructuralWorkflowRequest,
        unavailable: list[str],
    ) -> StructuralWorkflowResult:
        return StructuralWorkflowResult(
            run_id=run_id,
            status=RunStatus.FAILED,
            engine="Dockshift structural workflow",
            warnings=[f"Required prerequisites unavailable: {', '.join(unavailable)}"],
            provenance={"candidate_count": len(request.candidates)},
            preflight=preflight,
            pocket_plan_artifact=request.pocket_approval.proposal_artifact,
            pocket_plan_sha256=request.pocket_approval.proposal_sha256,
            literature_checkpoint=request.after_qsar_literature_checkpoint,
            md_next_step=cls._md_next_step(),
        )
