"""Integrated agent runs share Dockshift's authenticated execution boundary."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import authorize_structural_rest
from app.integration.models import RunRequest
from app.integration.service import IntegrationService

router = APIRouter(prefix="/agents", tags=["scientific agents"])


def service(request: Request) -> IntegrationService:
    return request.app.state.integration_service


Service = Annotated[IntegrationService, Depends(service)]


@router.get("/capabilities")
async def capabilities(integration: Service):
    return await integration.capabilities()


@router.post("/runs", dependencies=[Depends(authorize_structural_rest)])
async def run(request: RunRequest, integration: Service):
    return await integration.run(request)


@router.get("/runs/{run_id}", dependencies=[Depends(authorize_structural_rest)])
async def report(run_id: str, integration: Service):
    try:
        return integration.report(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/research", status_code=202, dependencies=[Depends(authorize_structural_rest)])
async def research(request: RunRequest, integration: Service):
    return await integration.start(request)


@router.get("/runs/{run_id}/progress", dependencies=[Depends(authorize_structural_rest)])
async def progress(run_id: str, integration: Service):
    try:
        return integration.progress(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post(
    "/runs/{run_id}/resume", status_code=202, dependencies=[Depends(authorize_structural_rest)]
)
async def resume(run_id: str, integration: Service):
    try:
        return await integration.resume(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/runs/{run_id}/artifacts/{name}", dependencies=[Depends(authorize_structural_rest)])
async def artifact(run_id: str, name: str, integration: Service):
    from fastapi.responses import FileResponse

    try:
        path = integration.artifact(run_id, name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, filename=name, media_type="application/octet-stream")
