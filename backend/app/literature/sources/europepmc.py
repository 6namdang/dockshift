"""Europe PMC: keyword search over bioRxiv preprints, plus full text (JATS XML).

bioRxiv's own API cannot search by keyword, so bioRxiv is searched through Europe PMC's
preprint index (``SRC:PPR AND PUBLISHER:"bioRxiv"``). Europe PMC also serves open-access
full text for PubMed Central articles, which the PubMed source reuses.

(ChemRxiv is *not* searched here: Europe PMC stopped indexing it in 2021. See chemrxiv.py.)
"""

from __future__ import annotations

from typing import Any

from app.literature.http import SourceUnavailableError, request
from app.literature.models import Document, Source
from app.literature.sources.base import LiteratureSource, SourceResult
from app.literature.text import clean_html, jats_to_text

EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
MAX_AUTHORS = 25


def date_filter(year_from: int | None, year_to: int | None) -> str:
    if not year_from and not year_to:
        return ""
    start = f"{year_from or 1800}-01-01"
    end = f"{year_to or 2100}-12-31"
    return f" AND FIRST_PDATE:[{start} TO {end}]"


async def fetch_europepmc_full_text(source: LiteratureSource, epmc_id: str) -> str | None:
    """Full text for a PMCID (``PMC123``) or preprint id (``PPR123``); None if not available."""
    try:
        response = await request(
            source.client,
            "GET",
            f"{EUROPE_PMC_BASE}/{epmc_id}/fullTextXML",
            # A 500 here usually means "no full text", so don't spend long retrying it.
            max_retries=min(1, source.settings.http_max_retries),
            label="Europe PMC full text",
        )
    except SourceUnavailableError as exc:
        # Europe PMC answers 404 (and sometimes 500) when it holds no full text for an id.
        if "HTTP 404" in str(exc) or "HTTP 500" in str(exc):
            return None
        raise
    text = jats_to_text(response.text)
    return text or None


class EuropePMCPreprintSource(LiteratureSource):
    """A preprint server indexed by Europe PMC. Subclasses set ``source`` and ``publisher``."""

    publisher: str
    venue: str

    def build_query(self, query: str, year_from: int | None, year_to: int | None) -> str:
        return f'({query}) AND SRC:PPR AND PUBLISHER:"{self.publisher}"' + date_filter(
            year_from, year_to
        )

    async def search(
        self,
        query: str,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> SourceResult:
        response = await request(
            self.client,
            "GET",
            f"{EUROPE_PMC_BASE}/search",
            params={
                "query": self.build_query(query, year_from, year_to),
                "format": "json",
                "resultType": "core",
                "pageSize": limit,
            },
            max_retries=self.settings.http_max_retries,
            label=f"Europe PMC ({self.venue})",
        )
        try:
            payload = response.json()
            hits = payload.get("resultList", {}).get("result", [])
            total = int(payload.get("hitCount", len(hits)))
        except (ValueError, AttributeError) as exc:
            raise SourceUnavailableError(
                f"Europe PMC returned an unexpected response: {exc}"
            ) from exc
        return SourceResult(total=total, documents=[self.parse_hit(h) for h in hits[:limit]])

    def parse_hit(self, hit: dict[str, Any]) -> Document:
        epmc_id = hit.get("id", "")
        doi = hit.get("doi")
        authors = [
            a.get("fullName") or a.get("collectiveName") or ""
            for a in (hit.get("authorList") or {}).get("author", [])
        ]
        authors = [a for a in authors if a]
        if not authors and hit.get("authorString"):
            authors = [a.strip() for a in hit["authorString"].rstrip(".").split(",") if a.strip()]
        version = (hit.get("bookOrReportDetails") or {}).get("edition")
        metadata: dict[str, Any] = {}
        if version:
            metadata["version"] = version
        return Document(
            id=self.make_id(epmc_id),
            source=self.source,
            title=clean_html(hit.get("title")) or "(untitled)",
            authors=authors[:MAX_AUTHORS],
            abstract=clean_html(hit.get("abstractText")),
            published_date=hit.get("firstPublicationDate") or hit.get("pubYear"),
            venue=self.venue,
            doi=doi,
            url=f"https://doi.org/{doi}" if doi else f"https://europepmc.org/article/PPR/{epmc_id}",
            identifiers={k: v for k, v in {"epmc_id": epmc_id, "doi": doi}.items() if v},
            metadata=metadata,
            full_text_available=hit.get("inEPMC") == "Y",
        )

    async def fetch_full_text(self, native_id: str, document: Document | None = None) -> str | None:
        return await fetch_europepmc_full_text(self, native_id)


class BioRxivSource(EuropePMCPreprintSource):
    source = Source.BIORXIV
    publisher = "bioRxiv"
    venue = "bioRxiv"
