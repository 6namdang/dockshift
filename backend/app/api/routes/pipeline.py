from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agent import (
    DEFAULT_SHORTLIST,
    CandidateProposal,
    LLMError,
    LLMNotConfiguredError,
    PipelineService,
    ShortlistResponse,
    Target,
)
from app.api.deps import get_pipeline_service

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

ServiceDep = Annotated[PipelineService, Depends(get_pipeline_service)]
CountQuery = Annotated[int, Query(ge=1, le=12, description="How many candidates to shortlist.")]


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, LLMNotConfiguredError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/targets", response_model=list[Target])
async def list_targets(service: ServiceDep) -> list[Target]:
    """Targets that can be screened, and whether each has a QSAR model."""
    return service.targets()


@router.post("/{target_id}/literature-shortlist", response_model=ShortlistResponse)
async def literature_shortlist(
    service: ServiceDep,
    target_id: str,
    count: CountQuery = DEFAULT_SHORTLIST,
    query: Annotated[
        str | None, Query(description="Literature query; defaults to the target's own.")
    ] = None,
) -> ShortlistResponse:
    """Search the literature, extract small molecules, score and rank them."""
    try:
        return await service.literature_shortlist(target_id, count, query)
    except (LLMNotConfiguredError, LLMError, ValueError) as exc:
        raise _handle(exc) from exc


@router.post("/{target_id}/candidates", response_model=CandidateProposal)
async def propose_candidates(
    service: ServiceDep, target_id: str, count: CountQuery = DEFAULT_SHORTLIST
) -> CandidateProposal:
    """Step 2 only: read the literature and propose candidate inhibitors (no scoring)."""
    try:
        return await service.propose_candidates(target_id, count)
    except (LLMNotConfiguredError, LLMError, ValueError) as exc:
        raise _handle(exc) from exc


@router.post("/{target_id}/shortlist", response_model=ShortlistResponse)
async def shortlist(
    service: ServiceDep,
    target_id: str,
    count: CountQuery = DEFAULT_SHORTLIST,
) -> ShortlistResponse:
    """Score the target's candidate molecules and rank them by predicted potency."""
    try:
        return await service.shortlist(target_id, count)
    except (LLMNotConfiguredError, LLMError, ValueError) as exc:
        raise _handle(exc) from exc
