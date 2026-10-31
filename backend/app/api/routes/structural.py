"""REST entry points for configured structural engines."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import authorize_structural_rest, get_structural_service
from app.structural import (
    AlphaFold3Request,
    AlphaFold3Result,
    CapabilitiesResult,
    DockingRequest,
    DockingResult,
    FPocketRequest,
    FPocketResult,
    GromacsRequest,
    GromacsResult,
    LigandPreparationRequest,
    LigandPreparationResult,
    PocketComparisonRequest,
    PocketComparisonResult,
    PocketPlanRequest,
    PocketPlanResult,
    ReceptorPreparationRequest,
    ReceptorPreparationResult,
    StructuralService,
    StructuralWorkflowRequest,
    StructuralWorkflowResult,
    TMAlignRequest,
    TMAlignResult,
)
from app.structural.errors import StructuralError
from app.structural.models import DockingBox, PocketBoxRequest

router = APIRouter(prefix="/structural", tags=["structural"])
ServiceDep = Annotated[StructuralService, Depends(get_structural_service)]
ExecutionAuth = Annotated[None, Depends(authorize_structural_rest)]
ResultT = TypeVar("ResultT")


async def _execute(operation: Awaitable[ResultT]) -> ResultT:
    try:
        return await operation
    except StructuralError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.as_dict()) from exc


@router.get("/capabilities", response_model=CapabilitiesResult)
async def capabilities(service: ServiceDep, _auth: ExecutionAuth) -> CapabilitiesResult:
    """Probe configured engines after structural REST authentication."""
    return await service.capabilities()


@router.post("/tmalign", response_model=TMAlignResult)
async def tmalign(
    request: TMAlignRequest, service: ServiceDep, _auth: ExecutionAuth
) -> TMAlignResult:
    return await _execute(service.tmalign(request))


@router.post("/alphafold3", response_model=AlphaFold3Result)
async def alphafold3(
    request: AlphaFold3Request, service: ServiceDep, _auth: ExecutionAuth
) -> AlphaFold3Result:
    return await _execute(service.alphafold3(request))


@router.post("/prepare/ligand", response_model=LigandPreparationResult)
async def prepare_ligand(
    request: LigandPreparationRequest, service: ServiceDep, _auth: ExecutionAuth
) -> LigandPreparationResult:
    return await _execute(service.prepare_ligand(request))


@router.post("/prepare/receptor", response_model=ReceptorPreparationResult)
async def prepare_receptor(
    request: ReceptorPreparationRequest, service: ServiceDep, _auth: ExecutionAuth
) -> ReceptorPreparationResult:
    return await _execute(service.prepare_receptor(request))


@router.post("/fpocket", response_model=FPocketResult)
async def fpocket(
    request: FPocketRequest, service: ServiceDep, _auth: ExecutionAuth
) -> FPocketResult:
    return await _execute(service.fpocket(request))


@router.post("/pockets/compare", response_model=PocketComparisonResult)
async def compare_pockets(
    request: PocketComparisonRequest, service: ServiceDep, _auth: ExecutionAuth
) -> PocketComparisonResult:
    return await _execute(service.compare_pockets(request))


@router.post("/pockets/box", response_model=DockingBox)
async def pocket_box(
    request: PocketBoxRequest, service: ServiceDep, _auth: ExecutionAuth
) -> DockingBox:
    return await _execute(service.pocket_box(request))


@router.post("/pockets/plan", response_model=PocketPlanResult)
async def create_pocket_plan(
    request: PocketPlanRequest, service: ServiceDep, _auth: ExecutionAuth
) -> PocketPlanResult:
    return await _execute(service.create_pocket_plan(request))


@router.post("/vina/dock", response_model=DockingResult)
async def dock(request: DockingRequest, service: ServiceDep, _auth: ExecutionAuth) -> DockingResult:
    return await _execute(service.dock(request))


@router.post("/workflow", response_model=StructuralWorkflowResult)
async def workflow(
    request: StructuralWorkflowRequest, service: ServiceDep, _auth: ExecutionAuth
) -> StructuralWorkflowResult:
    return await _execute(service.run_workflow(request))


@router.post("/gromacs/run", response_model=GromacsResult)
async def run_gromacs(
    request: GromacsRequest, service: ServiceDep, _auth: ExecutionAuth
) -> GromacsResult:
    return await _execute(service.run_gromacs(request))
