"""Patents via the Lens.org Patent API (global coverage: US, EP, WO, CN, JP, ...).

Docs: https://docs.api.lens.org/request-patent.html  /  response-patent.html
Auth: ``Authorization: Bearer <LENS_API_TOKEN>``.
"""

from __future__ import annotations

from typing import Any

from app.literature.http import SourceNotConfiguredError, SourceUnavailableError, request
from app.literature.models import Document, Source
from app.literature.sources.base import LiteratureSource, SourceResult

LENS_SEARCH_URL = "https://api.lens.org/patent/search"
MAX_PEOPLE = 25
SEARCH_FIELDS = ["title", "abstract", "claim"]
# Heavy fields we don't need in search results (we fetch claims/description on demand).
SEARCH_EXCLUDE = [
    "claims",
    "description",
    "families",
    "legal_status",
    "biblio.references_cited",
    "biblio.cited_by",
    "sequence_listing",
]


def _pick_lang(entries: Any, key: str = "text") -> str | None:
    """Lens returns multilingual fields as [{text, lang}]; prefer English."""
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list) or not entries:
        return None
    english = [e for e in entries if str(e.get("lang", "")).lower() == "en"]
    chosen = (english or entries)[0]
    value = chosen.get(key)
    return value.strip() if isinstance(value, str) else None


def _names(parties: list[dict[str, Any]] | None) -> list[str]:
    names = []
    for party in parties or []:
        value = (party.get("extracted_name") or {}).get("value")
        if value and value not in names:
            names.append(value)
    return names[:MAX_PEOPLE]


class PatentSource(LiteratureSource):
    source = Source.PATENTS

    def _headers(self) -> dict[str, str]:
        if not self.settings.lens_api_token:
            raise SourceNotConfiguredError(
                "Patent search needs LENS_API_TOKEN in backend/.env (request one at lens.org)."
            )
        return {
            "Authorization": f"Bearer {self.settings.lens_api_token}",
            "Content-Type": "application/json",
        }

    async def _post(self, body: dict[str, Any], label: str) -> dict[str, Any]:
        response = await request(
            self.client,
            "POST",
            LENS_SEARCH_URL,
            json=body,
            headers=self._headers(),
            max_retries=self.settings.http_max_retries,
            label=label,
        )
        if response.status_code == 204:  # Lens: no (more) results
            return {"total": 0, "data": []}
        try:
            return response.json()
        except ValueError as exc:
            raise SourceUnavailableError(f"Lens returned invalid JSON: {exc}") from exc

    async def search(
        self,
        query: str,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> SourceResult:
        bool_query: dict[str, Any] = {
            "must": [
                {
                    "query_string": {
                        "query": query,
                        "fields": SEARCH_FIELDS,
                        "default_operator": "and",
                    }
                }
            ]
        }
        if year_from or year_to:
            date_range: dict[str, str] = {}
            if year_from:
                date_range["gte"] = f"{year_from}-01-01"
            if year_to:
                date_range["lte"] = f"{year_to}-12-31"
            bool_query["filter"] = [{"range": {"date_published": date_range}}]

        payload = await self._post(
            {
                "query": {"bool": bool_query},
                "size": limit,
                "sort": [{"relevance": "desc"}],
                "exclude": SEARCH_EXCLUDE,
            },
            label="Lens patent search",
        )
        records = payload.get("data") or []
        total = int(payload.get("total", len(records)))
        return SourceResult(total=total, documents=[self.parse_record(r) for r in records[:limit]])

    def parse_record(self, record: dict[str, Any]) -> Document:
        lens_id = record.get("lens_id", "")
        biblio = record.get("biblio") or {}
        parties = biblio.get("parties") or {}
        jurisdiction = record.get("jurisdiction") or ""
        doc_number = record.get("doc_number") or ""
        kind = record.get("kind") or ""
        publication_number = f"{jurisdiction}{doc_number}{kind}" if doc_number else None

        metadata: dict[str, Any] = {
            "applicants": _names(parties.get("applicants")),
            "publication_type": record.get("publication_type"),
        }
        metadata = {k: v for k, v in metadata.items() if v}

        identifiers = {"lens_id": lens_id}
        if publication_number:
            identifiers["publication_number"] = publication_number

        return Document(
            id=self.make_id(lens_id),
            source=self.source,
            title=_pick_lang(biblio.get("invention_title")) or "(untitled patent)",
            authors=_names(parties.get("inventors")),
            abstract=_pick_lang(record.get("abstract")),
            published_date=record.get("date_published"),
            venue=f"{jurisdiction} patent office" if jurisdiction else "Patent",
            doi=None,
            url=f"https://www.lens.org/lens/patent/{lens_id}",
            identifiers=identifiers,
            metadata=metadata,
            full_text_available=True,  # claims/description are fetched from Lens on demand
        )

    async def fetch_full_text(self, native_id: str, document: Document | None = None) -> str | None:
        payload = await self._post(
            {"query": {"term": {"lens_id": native_id}}, "size": 1},
            label="Lens patent full text",
        )
        records = payload.get("data") or []
        if not records:
            return None
        return self.record_full_text(records[0])

    @staticmethod
    def record_full_text(record: dict[str, Any]) -> str | None:
        parts: list[str] = []
        title = _pick_lang((record.get("biblio") or {}).get("invention_title"))
        if title:
            parts.append(title)
        abstract = _pick_lang(record.get("abstract"))
        if abstract:
            parts.append("ABSTRACT\n" + abstract)

        claims_blocks = record.get("claims") or []
        english = [c for c in claims_blocks if str(c.get("lang", "")).lower() == "en"]
        block = (english or claims_blocks or [{}])[0]
        claim_texts = [
            " ".join(t for t in claim.get("claim_text", []) if t).strip()
            for claim in block.get("claims", [])
        ]
        claim_texts = [c for c in claim_texts if c]
        if claim_texts:
            parts.append("CLAIMS\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(claim_texts, 1)))

        description = _pick_lang(record.get("description"))
        if description:
            parts.append("DESCRIPTION\n" + description)
        return "\n\n".join(parts) if len(parts) > 1 else None
