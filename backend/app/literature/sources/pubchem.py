"""PubChem via NCBI PUG-REST (compound search by name, then property + description lookup).

PubChem (https://pubchem.ncbi.nlm.nih.gov/) is NCBI's chemistry database. Unlike the
literature sources, its records are *compounds*, not papers: there are no authors or
publication dates, so those Document fields stay empty. We treat each compound as a hit
whose "abstract" is its PubChem description and whose metadata carries the chemistry
(molecular formula, weight, IUPAC name, SMILES).

Search: ``/compound/name/{query}/cids/JSON`` resolves a query to compound ids (CIDs),
ordered by PubChem's own relevance. Details come from the ``property`` and ``description``
endpoints. Full text is the compound description served by PubChem.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.literature.http import SourceUnavailableError, request
from app.literature.models import Document, Source
from app.literature.sources.base import LiteratureSource, SourceResult

PUG_REST_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_COMPOUND_URL = "https://pubchem.ncbi.nlm.nih.gov/compound"
PROPERTIES = "Title,MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,InChIKey"


class PubChemSource(LiteratureSource):
    source = Source.PUBCHEM

    def _common_params(self) -> dict[str, str]:
        params = {"tool": "dockshift"}
        if self.settings.contact_email:
            params["email"] = self.settings.contact_email
        if self.settings.ncbi_api_key:
            params["api_key"] = self.settings.ncbi_api_key
        return params

    async def search(
        self,
        query: str,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> SourceResult:
        # PubChem compounds have no publication date, so year_from/year_to do not apply.
        cids = await self._search_cids(query)
        if not cids:
            return SourceResult(total=0, documents=[])
        total = len(cids)
        wanted = cids[:limit]
        properties = await self._fetch_properties(wanted)
        descriptions = await self._fetch_descriptions(wanted)
        documents = [
            self._build_document(cid, properties.get(cid, {}), descriptions.get(cid))
            for cid in wanted
        ]
        return SourceResult(total=total, documents=documents)

    async def _search_cids(self, query: str) -> list[int]:
        try:
            response = await request(
                self.client,
                "GET",
                f"{PUG_REST_BASE}/compound/name/{quote(query, safe='')}/cids/JSON",
                params=self._common_params(),
                max_retries=self.settings.http_max_retries,
                label="PubChem name search",
            )
        except SourceUnavailableError as exc:
            # PubChem answers 404 when no compound matches the queried name.
            if "HTTP 404" in str(exc):
                return []
            raise
        try:
            cids = response.json().get("IdentifierList", {}).get("CID", [])
        except ValueError as exc:
            raise SourceUnavailableError(
                f"PubChem name search returned an unexpected response: {exc}"
            ) from exc
        return [int(cid) for cid in cids]

    async def _fetch_properties(self, cids: list[int]) -> dict[int, dict[str, Any]]:
        ids = ",".join(str(cid) for cid in cids)
        response = await request(
            self.client,
            "GET",
            f"{PUG_REST_BASE}/compound/cid/{ids}/property/{PROPERTIES}/JSON",
            params=self._common_params(),
            max_retries=self.settings.http_max_retries,
            label="PubChem property lookup",
        )
        try:
            props = response.json().get("PropertyTable", {}).get("Properties", [])
        except ValueError as exc:
            raise SourceUnavailableError(
                f"PubChem property lookup returned an unexpected response: {exc}"
            ) from exc
        return {int(p["CID"]): p for p in props if p.get("CID") is not None}

    async def _fetch_descriptions(self, cids: list[int]) -> dict[int, str]:
        ids = ",".join(str(cid) for cid in cids)
        try:
            response = await request(
                self.client,
                "GET",
                f"{PUG_REST_BASE}/compound/cid/{ids}/description/JSON",
                params=self._common_params(),
                max_retries=self.settings.http_max_retries,
                label="PubChem description lookup",
            )
        except SourceUnavailableError as exc:
            # Descriptions are optional; a failure here must not sink the whole search.
            if "HTTP 404" in str(exc):
                return {}
            raise
        try:
            entries = response.json().get("InformationList", {}).get("Information", [])
        except ValueError as exc:
            raise SourceUnavailableError(
                f"PubChem description lookup returned an unexpected response: {exc}"
            ) from exc
        descriptions: dict[int, str] = {}
        for entry in entries:
            cid = entry.get("CID")
            text = entry.get("Description")
            if cid is not None and text and int(cid) not in descriptions:
                descriptions[int(cid)] = text
        return descriptions

    def _build_document(self, cid: int, props: dict[str, Any], description: str | None) -> Document:
        cid_str = str(cid)
        formula = props.get("MolecularFormula")
        weight = props.get("MolecularWeight")
        iupac = props.get("IUPACName")
        smiles = props.get("CanonicalSMILES")
        inchikey = props.get("InChIKey")
        title = props.get("Title") or iupac or f"CID {cid_str}"

        metadata: dict[str, Any] = {
            "molecular_formula": formula,
            "molecular_weight": str(weight) if weight is not None else None,
            "iupac_name": iupac,
            "canonical_smiles": smiles,
            "inchikey": inchikey,
        }
        metadata = {k: v for k, v in metadata.items() if v}

        identifiers = {k: v for k, v in {"cid": cid_str, "inchikey": inchikey}.items() if v}

        return Document(
            id=self.make_id(cid_str),
            source=self.source,
            title=title,
            authors=[],
            abstract=description,
            published_date=None,
            venue="PubChem",
            doi=None,
            url=f"{PUBCHEM_COMPOUND_URL}/{cid_str}",
            identifiers=identifiers,
            metadata=metadata,
            full_text_available=bool(description),
        )

    async def fetch_full_text(self, native_id: str, document: Document | None = None) -> str | None:
        if document is not None and document.abstract:
            return document.abstract
        descriptions = await self._fetch_descriptions([int(native_id)])
        return descriptions.get(int(native_id))
