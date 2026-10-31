from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_qsar_service
from app.qsar import ActivityResponse, DatasetSearchResult, ProfileResponse, QsarService
from app.qsar.models import MAX_COMPOUNDS

router = APIRouter(prefix="/qsar/htert", tags=["qsar"])

ServiceDep = Annotated[QsarService, Depends(get_qsar_service)]
CompoundsBody = Annotated[
    list[str],
    Body(
        min_length=1,
        max_length=MAX_COMPOUNDS,
        description="Compound names or SMILES strings.",
        examples=[["quercetin", "EGCG"]],
    ),
]


@router.post("/predict", response_model=ActivityResponse)
async def predict_activity(service: ServiceDep, compounds: CompoundsBody) -> ActivityResponse:
    """Predict hTERT inhibition potency (pIC50) for one or more compounds."""
    try:
        return await service.predict_activity(compounds)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/profile", response_model=ProfileResponse)
async def profile_compounds(service: ServiceDep, compounds: CompoundsBody) -> ProfileResponse:
    """Physicochemical and drug-likeness properties (QED, Lipinski, Veber)."""
    try:
        return await service.profile(compounds)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dataset", response_model=DatasetSearchResult)
async def search_dataset(
    service: ServiceDep,
    compound: Annotated[str, Query(min_length=1, description="Compound name or SMILES.")],
    limit: Annotated[int, Query(ge=1, le=25)] = 5,
) -> DatasetSearchResult:
    """Find measured hTERT compounds by exact structure or Tanimoto similarity."""
    return await service.search_dataset(compound, limit)


@router.get("/model")
async def model_info(service: ServiceDep) -> dict[str, Any]:
    """Model provenance: training data, performance, applicability domain, citation."""
    return await service.model_info()
