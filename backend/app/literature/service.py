"""Fan out a search to every source, merge and score hits, fetch full text when confident."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.config import Settings, get_settings
from app.literature.http import (
    SourceNotConfiguredError,
    SourceUnavailableError,
    build_http_client,
)
from app.literature.models import (
    Document,
    FullTextMode,
    FullTextResult,
    SearchRequest,
    SearchResponse,
    Source,
    SourceError,
)
from app.literature.scoring import score_documents
from app.literature.sources.base import LiteratureSource, SourceResult
from app.literature.sources.chemrxiv import ChemRxivSource
from app.literature.sources.europepmc import BioRxivSource
from app.literature.sources.pubchem import PubChemSource
from app.literature.sources.pubmed import PubMedSource
from app.literature.text import truncate

logger = logging.getLogger(__name__)

SOURCE_CLASSES: dict[Source, type[LiteratureSource]] = {
    Source.PUBMED: PubMedSource,
    Source.BIORXIV: BioRxivSource,
    Source.CHEMRXIV: ChemRxivSource,
    Source.PUBCHEM: PubChemSource,
}


class LiteratureSearchService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.sources: dict[Source, LiteratureSource] = {
            source: cls(client, self.settings) for source, cls in SOURCE_CLASSES.items()
        }

    # ------------------------------------------------------------------ search
    async def search(self, req: SearchRequest) -> SearchResponse:
        limit = min(req.max_results_per_source, self.settings.max_results_per_source_limit)
        outcomes = await asyncio.gather(
            *(
                self.sources[s].search(req.query, limit, req.year_from, req.year_to)
                for s in req.sources
            ),
            return_exceptions=True,
        )

        documents: list[Document] = []
        total_hits: dict[Source, int] = {}
        errors: list[SourceError] = []
        for source, outcome in zip(req.sources, outcomes, strict=True):
            if isinstance(outcome, SourceResult):
                total_hits[source] = outcome.total
                documents.extend(outcome.documents)
            else:
                errors.append(SourceError(source=source, message=_error_message(outcome)))

        documents = _dedupe(documents)
        score_documents(req.query, documents)
        documents.sort(key=lambda d: d.confidence or 0.0, reverse=True)

        if req.full_text is FullTextMode.AUTO:
            await self._attach_full_text(documents)

        return SearchResponse(
            query=req.query,
            results=documents,
            total_hits=total_hits,
            errors=errors,
            full_text_threshold=self.settings.fulltext_confidence_threshold,
        )

    async def _attach_full_text(self, documents: list[Document]) -> None:
        threshold = self.settings.fulltext_confidence_threshold
        candidates = [
            d for d in documents if d.full_text_available and (d.confidence or 0.0) >= threshold
        ][: self.settings.fulltext_max_docs]
        await asyncio.gather(*(self._fill_full_text(d) for d in candidates))

    async def _fill_full_text(self, doc: Document) -> None:
        try:
            text = await self.sources[doc.source].fetch_full_text(doc.native_id, doc)
        except Exception as exc:  # one failed full text must not sink the whole search
            doc.full_text_status = f"error: {_error_message(exc)}"
            return
        if not text:
            doc.full_text_status = "unavailable"
            return
        doc.full_text, doc.full_text_truncated = truncate(text, self.settings.fulltext_max_chars)
        doc.full_text_status = "fetched"

    # --------------------------------------------------------------- full text
    async def get_full_text(self, document_id: str) -> FullTextResult:
        source_name, _, native_id = document_id.partition(":")
        try:
            source = Source(source_name)
        except ValueError:
            return FullTextResult(
                id=document_id,
                available=False,
                message=f"Unknown source '{source_name}'. Ids look like 'pubmed:12345'.",
            )
        if not native_id:
            return FullTextResult(id=document_id, available=False, message="Missing id after ':'.")
        try:
            text = await self.sources[source].fetch_full_text(native_id)
        except Exception as exc:
            return FullTextResult(id=document_id, available=False, message=_error_message(exc))
        if not text:
            return FullTextResult(
                id=document_id,
                available=False,
                message="No open-access full text is available for this document.",
            )
        text, truncated = truncate(text, self.settings.fulltext_max_chars)
        return FullTextResult(id=document_id, available=True, full_text=text, truncated=truncated)


def _error_message(exc: BaseException) -> str:
    if isinstance(exc, SourceNotConfiguredError | SourceUnavailableError):
        return str(exc)
    logger.exception("Unexpected literature source error", exc_info=exc)
    return f"Unexpected error: {type(exc).__name__}: {exc}"


def _dedupe(documents: list[Document]) -> list[Document]:
    """Drop repeat DOIs (e.g. multiple preprint versions), keeping the first occurrence."""
    seen: set[str] = set()
    unique = []
    for doc in documents:
        key = doc.doi.lower() if doc.doi else doc.id
        if key in seen:
            continue
        seen.add(key)
        unique.append(doc)
    return unique


@asynccontextmanager
async def literature_service(
    settings: Settings | None = None,
) -> AsyncIterator[LiteratureSearchService]:
    """Create a service with its own HTTP client; closes the client on exit."""
    settings = settings or get_settings()
    async with build_http_client(settings) as client:
        yield LiteratureSearchService(client, settings)
