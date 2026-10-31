from __future__ import annotations

import respx

from app.literature.models import FullTextMode, SearchRequest, Source
from app.literature.service import LiteratureSearchService
from app.literature.sources.chemrxiv import CROSSREF_WORKS
from app.literature.sources.europepmc import EUROPE_PMC_BASE
from app.literature.sources.patents import LENS_SEARCH_URL
from app.literature.sources.pubchem import PUG_REST_BASE
from app.literature.sources.pubmed import EUTILS_BASE
from tests.conftest import make_settings
from tests.fixtures import payloads


def mock_all_sources() -> None:
    respx.get(f"{EUTILS_BASE}/esearch.fcgi").respond(json=payloads.ESEARCH_JSON)
    respx.post(f"{EUTILS_BASE}/efetch.fcgi").respond(text=payloads.EFETCH_XML)
    respx.get(f"{EUROPE_PMC_BASE}/search").respond(json=payloads.EUROPEPMC_BIORXIV_JSON)
    respx.get(CROSSREF_WORKS).respond(json=payloads.CROSSREF_CHEMRXIV_JSON)
    respx.post(LENS_SEARCH_URL).respond(json=payloads.LENS_SEARCH_JSON)
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/name/.*/cids/JSON").respond(
        json=payloads.PUBCHEM_CIDS_JSON
    )
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/cid/.*/property/.*").respond(
        json=payloads.PUBCHEM_PROPERTIES_JSON
    )
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/cid/.*/description/JSON").respond(
        json=payloads.PUBCHEM_DESCRIPTION_JSON
    )


@respx.mock
async def test_search_merges_all_sources_sorted_by_confidence(service):
    mock_all_sources()
    respx.get(url__regex=r".*/fullTextXML$").respond(text=payloads.JATS_XML)

    response = await service.search(
        SearchRequest(query="KRAS G12C covalent inhibitor", full_text=FullTextMode.NEVER)
    )

    assert response.errors == []
    assert response.total_hits == {
        Source.PUBMED: 2,
        Source.BIORXIV: 57,
        Source.CHEMRXIV: 3,
        Source.PATENTS: 1234,
        Source.PUBCHEM: 2,
    }
    assert {d.source for d in response.results} == set(Source)
    confidences = [d.confidence for d in response.results]
    assert confidences == sorted(confidences, reverse=True)
    assert response.results[-1].confidence < 0.2  # bananas / Diels-Alder sink to the bottom
    assert all(d.full_text is None and d.full_text_status is None for d in response.results)


@respx.mock
async def test_auto_full_text_only_for_confident_retrievable_hits(service):
    mock_all_sources()
    jats = respx.get(url__regex=r".*/fullTextXML$").respond(text=payloads.JATS_XML)
    lens_full = respx.post(LENS_SEARCH_URL)
    lens_full.side_effect = [
        respx.MockResponse(json=payloads.LENS_SEARCH_JSON),  # search
        respx.MockResponse(json=payloads.LENS_FULL_RECORD_JSON),  # full text
    ]

    response = await service.search(SearchRequest(query="KRAS G12C covalent inhibitor"))

    threshold = response.full_text_threshold
    for d in response.results:
        if d.full_text_status is not None:
            assert d.confidence >= threshold and d.full_text_available
        if d.confidence < threshold or not d.full_text_available:
            assert d.full_text is None and d.full_text_status is None
    fetched = [d for d in response.results if d.full_text_status == "fetched"]
    assert fetched, "expected at least one confident open-access hit to get full text"
    assert len(fetched) <= 3
    assert jats.called


@respx.mock
async def test_full_text_capped_by_max_docs(client):
    service = LiteratureSearchService(
        client, make_settings(fulltext_confidence_threshold=0.0, fulltext_max_docs=1)
    )
    mock_all_sources()
    jats = respx.get(url__regex=r".*/fullTextXML$").respond(text=payloads.JATS_XML)
    response = await service.search(
        SearchRequest(query="KRAS", sources=[Source.PUBMED, Source.BIORXIV])
    )
    assert sum(d.full_text_status is not None for d in response.results) == 1
    assert jats.call_count == 1


@respx.mock
async def test_one_failing_source_does_not_break_the_search(client):
    service = LiteratureSearchService(client, make_settings(lens_api_token=None))
    respx.get(f"{EUTILS_BASE}/esearch.fcgi").respond(status_code=500)
    respx.get(f"{EUROPE_PMC_BASE}/search").respond(json=payloads.EUROPEPMC_BIORXIV_JSON)
    respx.get(CROSSREF_WORKS).respond(json=payloads.CROSSREF_CHEMRXIV_JSON)
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/name/.*/cids/JSON").respond(
        json=payloads.PUBCHEM_CIDS_JSON
    )
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/cid/.*/property/.*").respond(
        json=payloads.PUBCHEM_PROPERTIES_JSON
    )
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/cid/.*/description/JSON").respond(
        json=payloads.PUBCHEM_DESCRIPTION_JSON
    )

    response = await service.search(SearchRequest(query="kras", full_text=FullTextMode.NEVER))

    errors = {e.source: e.message for e in response.errors}
    assert set(errors) == {Source.PUBMED, Source.PATENTS}
    assert "HTTP 500" in errors[Source.PUBMED]
    assert "LENS_API_TOKEN" in errors[Source.PATENTS]
    assert {d.source for d in response.results} == {
        Source.BIORXIV,
        Source.CHEMRXIV,
        Source.PUBCHEM,
    }


@respx.mock
async def test_full_text_error_is_reported_per_document(client):
    service = LiteratureSearchService(client, make_settings(fulltext_confidence_threshold=0.0))
    respx.get(f"{EUROPE_PMC_BASE}/search").respond(json=payloads.EUROPEPMC_BIORXIV_JSON)
    respx.get(f"{EUROPE_PMC_BASE}/PPR100/fullTextXML").respond(status_code=403)
    response = await service.search(SearchRequest(query="kras", sources=[Source.BIORXIV]))
    hit = next(d for d in response.results if d.id == "biorxiv:PPR100")
    assert hit.full_text is None and hit.full_text_status.startswith("error: ")


async def test_get_full_text_rejects_bad_ids(service):
    bad_source = await service.get_full_text("nature:123")
    assert not bad_source.available and "Unknown source" in bad_source.message
    missing = await service.get_full_text("pubmed:")
    assert not missing.available


@respx.mock
async def test_get_full_text_truncates(client):
    service = LiteratureSearchService(client, make_settings(fulltext_max_chars=40))
    respx.get(f"{EUROPE_PMC_BASE}/PPR100/fullTextXML").respond(text=payloads.JATS_XML)
    result = await service.get_full_text("biorxiv:PPR100")
    assert result.available and result.truncated and result.full_text.endswith("…[truncated]")


@respx.mock
async def test_get_full_text_unavailable_source_message(client):
    service = LiteratureSearchService(client, make_settings(lens_api_token=None))
    result = await service.get_full_text("patents:123")
    assert not result.available and "LENS_API_TOKEN" in result.message
