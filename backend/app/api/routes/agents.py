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
