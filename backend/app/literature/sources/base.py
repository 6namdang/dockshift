"""Interface every literature source implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from app.config import Settings
from app.literature.models import Document, Source


@dataclass
class SourceResult:
    total: int
    documents: list[Document] = field(default_factory=list)


class LiteratureSource(ABC):
    source: Source

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> SourceResult:
        """Return up to ``limit`` documents ordered by the source's own relevance ranking."""

    @abstractmethod
    async def fetch_full_text(self, native_id: str, document: Document | None = None) -> str | None:
        """Return plain full text, or None if the source has none for this document.

        ``document`` is the search hit when available, so implementations can reuse ids
        found during search instead of making extra lookups.
        """

    def make_id(self, native_id: str) -> str:
        return f"{self.source.value}:{native_id}"
