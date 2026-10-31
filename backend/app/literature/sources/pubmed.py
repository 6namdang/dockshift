"""PubMed via NCBI E-utilities (esearch -> efetch). Full text via Europe PMC for PMC articles."""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

from app.literature.http import SourceUnavailableError, request
from app.literature.models import Document, Source
from app.literature.sources.base import LiteratureSource, SourceResult
from app.literature.sources.europepmc import EUROPE_PMC_BASE, fetch_europepmc_full_text
from app.literature.text import element_text

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_AUTHORS = 25
_MONTHS = {
    m: f"{i:02d}"
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


def _month(value: str | None) -> str | None:
    if not value:
        return None
    if value.isdigit():
        return f"{int(value):02d}"
    return _MONTHS.get(value[:3].lower())


def _date(el: Element | None) -> str | None:
    """Turn a PubMed <PubDate>/<ArticleDate> into YYYY[-MM[-DD]]."""
    if el is None:
        return None
    year = el.findtext("Year")
    if not year:
        medline = el.findtext("MedlineDate") or ""  # e.g. "2019 Nov-Dec"
        return medline[:4] if medline[:4].isdigit() else None
    month = _month(el.findtext("Month"))
    day = el.findtext("Day")
    if month and day and day.isdigit():
        return f"{year}-{month}-{int(day):02d}"
    return f"{year}-{month}" if month else year


class PubMedSource(LiteratureSource):
    source = Source.PUBMED

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
        params: dict[str, Any] = {
            **self._common_params(),
            "db": "pubmed",
            "term": query,
            "retmax": limit,
            "retmode": "json",
            "sort": "relevance",
        }
        if year_from or year_to:
            params.update(
                datetype="pdat",
                mindate=f"{year_from or 1800}/01/01",
                maxdate=f"{year_to or 2100}/12/31",
            )
        response = await request(
            self.client,
            "GET",
            f"{EUTILS_BASE}/esearch.fcgi",
            params=params,
            max_retries=self.settings.http_max_retries,
            label="PubMed esearch",
        )
        try:
            result = response.json()["esearchresult"]
            pmids: list[str] = result.get("idlist", [])
            total = int(result.get("count", len(pmids)))
        except (ValueError, KeyError) as exc:
            raise SourceUnavailableError(
                f"PubMed esearch returned an unexpected response: {exc}"
            ) from exc
        if not pmids:
            return SourceResult(total=total, documents=[])

        documents = await self.fetch_records(pmids)
        order = {pmid: i for i, pmid in enumerate(pmids)}  # keep PubMed's relevance order
        documents.sort(key=lambda d: order.get(d.native_id, len(order)))
        return SourceResult(total=total, documents=documents)

    async def fetch_records(self, pmids: list[str]) -> list[Document]:
        response = await request(
            self.client,
            "POST",  # POST avoids URL-length limits for long id lists
            f"{EUTILS_BASE}/efetch.fcgi",
            data={**self._common_params(), "db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
            max_retries=self.settings.http_max_retries,
            label="PubMed efetch",
        )
        try:
            root = SafeET.fromstring(response.content)
        except SafeET.ParseError as exc:
            raise SourceUnavailableError(f"PubMed efetch returned invalid XML: {exc}") from exc
        return [self.parse_article(a) for a in root.iter("PubmedArticle")]

    def parse_article(self, article: Element) -> Document:
        citation = article.find("MedlineCitation")
        art = citation.find("Article") if citation is not None else None
        pmid = (citation.findtext("PMID") if citation is not None else None) or ""

        title = element_text(art.find("ArticleTitle")) if art is not None else ""

        abstract_parts = []
        for node in art.findall("Abstract/AbstractText") if art is not None else []:
            text = element_text(node)
            if text:
                label = node.get("Label")
                abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = "\n".join(abstract_parts) or None

        authors: list[str] = []
        for author in art.findall("AuthorList/Author") if art is not None else []:
            if author.findtext("CollectiveName"):
                authors.append(author.findtext("CollectiveName") or "")
                continue
            last = author.findtext("LastName")
            initials = author.findtext("Initials") or author.findtext("ForeName")
            if last:
                authors.append(f"{last} {initials}" if initials else last)

        published = None
        journal = None
        if art is not None:
            published = _date(art.find("ArticleDate")) or _date(
                art.find("Journal/JournalIssue/PubDate")
            )
            journal = art.findtext("Journal/Title")

        ids = {
            el.get("IdType"): (el.text or "").strip()
            for el in article.findall("PubmedData/ArticleIdList/ArticleId")
        }
        doi = ids.get("doi") or None
        pmcid = ids.get("pmc") or None

        mesh = [
            element_text(d)
            for d in (
                citation.findall("MeshHeadingList/MeshHeading/DescriptorName")
                if citation is not None
                else []
            )
        ]
        pub_types = (
            [element_text(p) for p in art.findall("PublicationTypeList/PublicationType")]
            if art is not None
            else []
        )
        metadata: dict[str, Any] = {}
        if mesh:
            metadata["mesh_terms"] = mesh[:20]
        if pub_types:
            metadata["publication_types"] = pub_types

        return Document(
            id=self.make_id(pmid),
            source=self.source,
            title=title or "(untitled)",
            authors=authors[:MAX_AUTHORS],
            abstract=abstract,
            published_date=published,
            venue=journal,
            doi=doi,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            identifiers={k: v for k, v in {"pmid": pmid, "pmcid": pmcid, "doi": doi}.items() if v},
            metadata=metadata,
            full_text_available=pmcid is not None,
        )

    async def _lookup_pmcid(self, pmid: str) -> str | None:
        response = await request(
            self.client,
            "GET",
            f"{EUROPE_PMC_BASE}/search",
            params={"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "resultType": "lite"},
            max_retries=self.settings.http_max_retries,
            label="Europe PMC id lookup",
        )
        hits = response.json().get("resultList", {}).get("result", [])
        return hits[0].get("pmcid") if hits else None

    async def fetch_full_text(self, native_id: str, document: Document | None = None) -> str | None:
        pmcid = document.identifiers.get("pmcid") if document else None
        if pmcid is None:
            pmcid = await self._lookup_pmcid(native_id)
        if not pmcid:
            return None
        return await fetch_europepmc_full_text(self, pmcid)
