"""ChemRxiv via the Crossref REST API (ChemRxiv DOI prefix 10.26434).

Why Crossref: ChemRxiv's own API is behind a Cloudflare bot challenge, and Europe PMC
stopped indexing ChemRxiv in 2021. Crossref has every ChemRxiv DOI with abstracts and
needs no key. ChemRxiv full text (PDF) sits behind Cloudflare too, so this source
returns metadata + abstracts only.
"""

from __future__ import annotations

import re
from typing import Any

from app.literature.http import SourceUnavailableError, request
from app.literature.models import Document, Source
from app.literature.sources.base import LiteratureSource, SourceResult
from app.literature.text import clean_html

CROSSREF_WORKS = "https://api.crossref.org/works"
CHEMRXIV_PREFIX = "10.26434"
MAX_AUTHORS = 25
MAX_ROWS = 100
_VERSION_RE = re.compile(r"(?:[-/.]v\d+)$", re.IGNORECASE)
SELECT = "DOI,title,abstract,posted,author,URL,license"


def base_doi(doi: str) -> str:
    """'10.26434/chemrxiv-2023-mq2p7-v2' -> '10.26434/chemrxiv-2023-mq2p7'."""
    return _VERSION_RE.sub("", doi.lower())


def _posted(item: dict[str, Any]) -> str | None:
    parts = ((item.get("posted") or {}).get("date-parts") or [[None]])[0]
    if not parts or parts[0] is None:
        return None
    return "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts))


class ChemRxivSource(LiteratureSource):
    source = Source.CHEMRXIV

    async def search(
        self,
        query: str,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> SourceResult:
        filters = [f"prefix:{CHEMRXIV_PREFIX}", "type:posted-content"]
        if year_from:
            filters.append(f"from-posted-date:{year_from}-01-01")
        if year_to:
            filters.append(f"until-posted-date:{year_to}-12-31")
        params: dict[str, Any] = {
            "query.bibliographic": query,
            "filter": ",".join(filters),
            # Each preprint version is its own DOI; over-fetch, then keep one per preprint.
            "rows": min(limit * 2, MAX_ROWS),
            "select": SELECT,
        }
        if self.settings.contact_email:
            params["mailto"] = self.settings.contact_email  # Crossref "polite pool"
        response = await request(
            self.client,
            "GET",
            CROSSREF_WORKS,
            params=params,
            max_retries=self.settings.http_max_retries,
            label="Crossref (ChemRxiv)",
        )
        try:
            message = response.json()["message"]
            items: list[dict[str, Any]] = message.get("items", [])
            total = int(message.get("total-results", len(items)))
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceUnavailableError(
                f"Crossref returned an unexpected response: {exc}"
            ) from exc

        # Keep the newest version of each preprint, in Crossref's relevance order.
        latest: dict[str, dict[str, Any]] = {}
        for item in items:
            key = base_doi(item.get("DOI", ""))
            current = latest.get(key)
            if current is None or (_posted(item) or "") > (_posted(current) or ""):
                latest[key] = item
        documents = [self.parse_item(item) for item in latest.values()][:limit]
        return SourceResult(total=total, documents=documents)

    def parse_item(self, item: dict[str, Any]) -> Document:
        doi = item.get("DOI", "")
        authors = []
        for author in item.get("author") or []:
            name = " ".join(p for p in (author.get("given"), author.get("family")) if p)
            name = name or author.get("name", "")
            if name:
                authors.append(name)
        licenses = [lic.get("URL") for lic in item.get("license") or [] if lic.get("URL")]
        return Document(
            id=self.make_id(doi),
            source=self.source,
            title=clean_html((item.get("title") or [""])[0]) or "(untitled)",
            authors=authors[:MAX_AUTHORS],
            abstract=clean_html(item.get("abstract")),
            published_date=_posted(item),
            venue="ChemRxiv",
            doi=doi,
            url=f"https://doi.org/{doi}",
            identifiers={"doi": doi},
            metadata={"license": licenses[0]} if licenses else {},
            full_text_available=False,
        )

    async def fetch_full_text(self, native_id: str, document: Document | None = None) -> str | None:
        return None  # ChemRxiv PDFs are behind a Cloudflare challenge; not retrievable.
