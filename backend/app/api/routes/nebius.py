from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_nebius_service
from app.nebius import DockingResult, NebiusError, NebiusNotConfiguredError, NebiusService
from app.nebius.service import RemoteEngineStatus, ThreeSiteResult

router = APIRouter(prefix="/remote", tags=["remote engines"])

ServiceDep = Annotated[NebiusService, Depends(get_nebius_service)]


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, NebiusNotConfiguredError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/engines", response_model=RemoteEngineStatus)
async def engines(service: ServiceDep) -> RemoteEngineStatus:
    """Which remote scientific engines are reachable."""
    return await service.engine_status()


@router.post("/dock", response_model=DockingResult)
async def dock(
    service: ServiceDep,
    smiles: Annotated[str, Query(min_length=1, description="Ligand SMILES.")],
    receptor_pdb: Annotated[str, Body(embed=True, description="Receptor PDB text.")],
    num_poses: Annotated[int, Query(ge=1, le=4, description="Server maximum is 4.")] = 4,
    wait_seconds: Annotated[int, Query(ge=0, le=30, description="Server maximum is 30.")] = 30,
) -> DockingResult:
    """Dock a ligand into a receptor with DiffDock, on the remote engine."""
    try:
        return await service.dock(smiles, receptor_pdb, num_poses, wait_seconds)
    except (NebiusError, NebiusNotConfiguredError, ValueError) as exc:
        raise _fail(exc) from exc


@router.get("/operations/{operation_id}")
async def operation(service: ServiceDep, operation_id: str) -> dict[str, Any]:
    """Poll a long-running remote job."""
    try:
        return await service.operation(operation_id)
    except (NebiusError, NebiusNotConfiguredError) as exc:
        raise _fail(exc) from exc


@router.get("/operations/{operation_id}/result")
async def operation_result(service: ServiceDep, operation_id: str) -> dict[str, Any]:
    """Fetch a finished remote job's verified result."""
    try:
        return await service.operation_result(operation_id)
    except (NebiusError, NebiusNotConfiguredError) as exc:
        raise _fail(exc) from exc


@router.post("/three-site-dock", response_model=ThreeSiteResult)
async def three_site_dock(
    service: ServiceDep,
    compounds: Annotated[
        dict[str, str],
        Body(
            embed=True,
            description="Compound name -> SMILES, up to 8.",
            examples=[{"quercetin": "O=c1c(O)c(-c2ccc(O)c(O)c2)oc2cc(O)cc(O)c12"}],
        ),
    ],
    radius: Annotated[
        float, Query(ge=8, le=30, description="Angstrom kept around each site.")
    ] = 18.0,
) -> ThreeSiteResult:
    """Dock the chosen compounds against all three sites on 9Q14."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as http:
            return await service.three_site_dock(compounds, radius=radius, http=http)
    except (NebiusError, NebiusNotConfiguredError, ValueError) as exc:
        raise _fail(exc) from exc


@router.get("/sites")
async def docking_sites(service: ServiceDep) -> dict[str, Any]:
    """The three sites on 9Q14, with their centroids."""
    import httpx

    from app.nebius.receptor import sites

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as http:
        from app.nebius.receptor import ensure_receptor

        await ensure_receptor(http, service.settings)
    return {
        "receptor": "9Q14",
        "sites": [
            {"id": s.id, "name": s.name, "description": s.description, "centroid": s.centroid}
            for s in sites()
        ],
    }
