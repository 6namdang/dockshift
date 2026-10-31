"""Pydantic models shared by the literature sources, the REST API and the MCP tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Source(StrEnum):
    PUBMED = "pubmed"
    BIORXIV = "biorxiv"
    CHEMRXIV = "chemrxiv"
    PATENTS = "patents"
    PUBCHEM = "pubchem"


ALL_SOURCES: list[Source] = list(Source)


class FullTextMode(StrEnum):
    AUTO = "auto"  # fetch full text for high-confidence, retrievable hits
    NEVER = "never"  # metadata + abstract only


class Document(BaseModel):
    """One search hit, normalised across sources."""

    id: str = Field(description="Stable id '<source>:<native id>'; pass it to get_full_text.")
    source: Source
    title: str
    authors: list[str] = Field(
        default_factory=list, description="Authors, or inventors for patents."
    )
    abstract: str | None = None
    published_date: str | None = Field(None, description="ISO date (YYYY-MM-DD, YYYY-MM or YYYY).")
    venue: str | None = Field(None, description="Journal, preprint server, or patent office.")
    doi: str | None = None
    url: str | None = None
    identifiers: dict[str, str] = Field(
        default_factory=dict, description="Native ids, e.g. pmid, pmcid, epmc_id, lens_id."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Source-specific extras, e.g. patent applicants."
    )
    full_text_available: bool = Field(
        False, description="Whether full text can likely be retrieved for this document."
    )
    confidence: float | None = Field(
        None, description="Lexical relevance to the query, 0-1 (higher = more relevant)."
    )
    full_text: str | None = None
    full_text_truncated: bool = False
    full_text_status: str | None = Field(
        None,
        description="None if not attempted; otherwise 'fetched', 'unavailable' or 'error: ...'.",
    )

    @property
    def native_id(self) -> str:
        return self.id.split(":", 1)[1]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    sources: list[Source] = Field(default_factory=lambda: list(ALL_SOURCES), min_length=1)
    max_results_per_source: int = Field(10, ge=1, le=50)
    year_from: int | None = Field(None, ge=1800, le=2100)
    year_to: int | None = Field(None, ge=1800, le=2100)
    full_text: FullTextMode = FullTextMode.AUTO

    @model_validator(mode="after")
    def _check(self) -> SearchRequest:
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must be <= year_to")
        self.sources = list(dict.fromkeys(self.sources))  # de-duplicate, keep order
        if not self.query.strip():
            raise ValueError("query must not be blank")
        return self


class SourceError(BaseModel):
    source: Source
    message: str


class SearchResponse(BaseModel):
    query: str
    results: list[Document]
    total_hits: dict[Source, int] = Field(
        default_factory=dict,
        description="Total matches reported by each source (not just returned).",
    )
    errors: list[SourceError] = Field(default_factory=list)
    full_text_threshold: float


class FullTextResult(BaseModel):
    id: str
    available: bool
    full_text: str | None = None
    truncated: bool = False
    message: str | None = None
