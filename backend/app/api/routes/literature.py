from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_literature_service
from app.literature import FullTextResult, LiteratureSearchService, SearchRequest, SearchResponse

router = APIRouter(prefix="/literature", tags=["literature"])

ServiceDep = Annotated[LiteratureSearchService, Depends(get_literature_service)]


@router.post("/search", response_model=SearchResponse)
async def search_literature(body: SearchRequest, service: ServiceDep) -> SearchResponse:
    """Search PubMed, bioRxiv, ChemRxiv and PubChem; ranked by lexical confidence."""
    return await service.search(body)


@router.get("/full-text/{document_id:path}", response_model=FullTextResult)
async def get_full_text(document_id: str, service: ServiceDep) -> FullTextResult:
    """Full text for one search result id, e.g. `pubmed:38012345`."""
    return await service.get_full_text(document_id)
