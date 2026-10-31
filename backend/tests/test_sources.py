from __future__ import annotations

import httpx
import pytest
import respx

from app.literature.http import SourceNotConfiguredError, SourceUnavailableError
from app.literature.models import Document, Source
from app.literature.sources.chemrxiv import CROSSREF_WORKS, ChemRxivSource, base_doi
from app.literature.sources.europepmc import EUROPE_PMC_BASE, BioRxivSource
from app.literature.sources.patents import LENS_SEARCH_URL, PatentSource
from app.literature.sources.pubchem import PUG_REST_BASE, PubChemSource
from app.literature.sources.pubmed import EUTILS_BASE, PubMedSource
from tests.conftest import make_settings
from tests.fixtures import payloads


# ---------------------------------------------------------------- PubMed
@respx.mock
async def test_pubmed_search_parses_records_in_relevance_order(client, settings):
    esearch = respx.get(f"{EUTILS_BASE}/esearch.fcgi").respond(json=payloads.ESEARCH_JSON)
    respx.post(f"{EUTILS_BASE}/efetch.fcgi").respond(text=payloads.EFETCH_XML)

    result = await PubMedSource(client, settings).search("kras", 5, year_from=2020, year_to=2022)

    params = esearch.calls.last.request.url.params
    assert params["term"] == "kras" and params["sort"] == "relevance"
    assert params["mindate"] == "2020/01/01" and params["maxdate"] == "2022/12/31"
    assert params["email"] == "test@example.com"

    assert result.total == 2
    first, second = result.documents
    assert [first.id, second.id] == ["pubmed:222", "pubmed:111"]  # esearch order, not efetch order
    assert first.title == "KRAS G12C covalent inhibitor docking study"
    assert first.abstract.startswith("BACKGROUND: KRAS G12C")
    assert "RESULTS: Docking" in first.abstract
    assert first.authors == ["Smith A", "KRAS Consortium"]
    assert first.published_date == "2021-03-07"
    assert first.identifiers == {"pmid": "222", "pmcid": "PMC999", "doi": "10.1000/kras"}
    assert first.full_text_available is True
    assert first.metadata["mesh_terms"] == ["Proto-Oncogene Proteins p21(ras)"]
    assert second.title == "Unrelated title about bananas"
    assert second.published_date == "2019-11"
    assert second.full_text_available is False


@respx.mock
async def test_pubmed_empty_result_skips_efetch(client, settings):
    respx.get(f"{EUTILS_BASE}/esearch.fcgi").respond(
        json={"esearchresult": {"count": "0", "idlist": []}}
    )
    efetch = respx.post(f"{EUTILS_BASE}/efetch.fcgi")
    result = await PubMedSource(client, settings).search("zzz", 5)
    assert result.total == 0 and result.documents == []
    assert not efetch.called


@respx.mock
async def test_pubmed_full_text_looks_up_pmcid_then_fetches_jats(client, settings):
    respx.get(f"{EUROPE_PMC_BASE}/search").respond(
        json={"resultList": {"result": [{"pmcid": "PMC42"}]}}
    )
    respx.get(f"{EUROPE_PMC_BASE}/PMC42/fullTextXML").respond(text=payloads.JATS_XML)
    text = await PubMedSource(client, settings).fetch_full_text("123")
    assert text and "## Methods" in text


@respx.mock
async def test_upstream_error_becomes_source_unavailable(client, settings):
    respx.get(f"{EUTILS_BASE}/esearch.fcgi").respond(status_code=503, text="down")
    with pytest.raises(SourceUnavailableError, match="HTTP 503"):
        await PubMedSource(client, settings).search("kras", 5)


@respx.mock
async def test_retries_transient_errors(client):
    settings = make_settings(http_max_retries=2)
    route = respx.get(f"{EUTILS_BASE}/esearch.fcgi")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.ConnectError("boom"),
        httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}}),
    ]
    result = await PubMedSource(client, settings).search("kras", 5)
    assert route.call_count == 3 and result.total == 0


# --------------------------------------------------------------- bioRxiv
@respx.mock
async def test_biorxiv_search_via_europepmc(client, settings):
    route = respx.get(f"{EUROPE_PMC_BASE}/search").respond(json=payloads.EUROPEPMC_BIORXIV_JSON)
    result = await BioRxivSource(client, settings).search("kras", 5, year_from=2024)

    query = route.calls.last.request.url.params["query"]
    assert (
        query
        == '(kras) AND SRC:PPR AND PUBLISHER:"bioRxiv" AND FIRST_PDATE:[2024-01-01 TO 2100-12-31]'
    )
    assert result.total == 57
    hit, other = result.documents
    assert hit.id == "biorxiv:PPR100"
    assert hit.title == "KRAS G12C covalent inhibitor docking"
    assert hit.abstract == "Abstract We dock KRAS G12C covalent inhibitors & more."
    assert hit.url == "https://doi.org/10.1101/2024.01.01.000001"
    assert hit.full_text_available is True and hit.metadata == {"version": "2"}
    assert other.authors == ["Roe C"] and other.abstract is None and not other.full_text_available


@respx.mock
async def test_europepmc_missing_full_text_returns_none(client, settings):
    respx.get(f"{EUROPE_PMC_BASE}/PPR1/fullTextXML").respond(status_code=404)
    assert await BioRxivSource(client, settings).fetch_full_text("PPR1") is None


# -------------------------------------------------------------- ChemRxiv
def test_base_doi_strips_version_suffixes():
    assert base_doi("10.26434/chemrxiv-2023-mq2p7-v2") == "10.26434/chemrxiv-2023-mq2p7"
    assert base_doi("10.26434/chemrxiv.9757583.v1") == "10.26434/chemrxiv.9757583"
    assert base_doi("10.26434/chemrxiv-2015-1") == "10.26434/chemrxiv-2015-1"


@respx.mock
async def test_chemrxiv_keeps_latest_version_per_preprint(client, settings):
    route = respx.get(CROSSREF_WORKS).respond(json=payloads.CROSSREF_CHEMRXIV_JSON)
    result = await ChemRxivSource(client, settings).search("kras", 5, year_from=2020, year_to=2025)

    params = route.calls.last.request.url.params
    assert params["filter"] == (
        "prefix:10.26434,type:posted-content,"
        "from-posted-date:2020-01-01,until-posted-date:2025-12-31"
    )
    assert params["mailto"] == "test@example.com"
    assert result.total == 3
    assert [d.id for d in result.documents] == [
        "chemrxiv:10.26434/chemrxiv-2023-abcde-v2",
        "chemrxiv:10.26434/chemrxiv.9757583.v1",
    ]
    latest = result.documents[0]
    assert latest.published_date == "2025-03-27"
    assert latest.abstract == "Updated version."
    assert latest.authors == ["Renne Leini"]
    assert result.documents[1].authors == ["Chem Group"]
    assert not latest.full_text_available


# --------------------------------------------------------------- Patents
@respx.mock
async def test_patent_search_parses_lens_records(client, settings):
    route = respx.post(LENS_SEARCH_URL).respond(json=payloads.LENS_SEARCH_JSON)
    result = await PatentSource(client, settings).search("kras", 7, year_from=2019)

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-token"
    body = httpx.Request("POST", "/", content=request.content).read()
    assert b'"fields":["title","abstract","claim"]' in body.replace(b" ", b"")
    assert b'"gte":"2019-01-01"' in body.replace(b" ", b"")
    assert b'"size":7' in body.replace(b" ", b"")

    assert result.total == 1234
    patent = result.documents[0]
    assert patent.id == "patents:031-156-664-516-153"
    assert patent.title == "Covalent KRAS G12C inhibitors"  # English preferred
    assert patent.authors == ["OCHOA JORGE", "SMITH ANNA"]
    assert patent.metadata["applicants"] == ["ACME PHARMA INC"]
    assert patent.identifiers["publication_number"] == "US11000000B2"
    assert patent.url == "https://www.lens.org/lens/patent/031-156-664-516-153"


async def test_patents_without_token_raise_not_configured(client):
    source = PatentSource(client, make_settings(lens_api_token=None))
    with pytest.raises(SourceNotConfiguredError, match="LENS_API_TOKEN"):
        await source.search("kras", 5)


@respx.mock
async def test_patent_full_text_includes_claims_and_description(client, settings):
    respx.post(LENS_SEARCH_URL).respond(json=payloads.LENS_FULL_RECORD_JSON)
    text = await PatentSource(client, settings).fetch_full_text("031-156-664-516-153")
    assert "CLAIMS\n1. A compound of formula (I).\n2. The compound of claim 1" in text
    assert "DESCRIPTION\nField of the invention." in text


# -------------------------------------------------------------- PubChem
@respx.mock
async def test_pubchem_search_parses_compounds_in_relevance_order(client, settings):
    cids = respx.get(url__regex=rf"{PUG_REST_BASE}/compound/name/.*/cids/JSON").respond(
        json=payloads.PUBCHEM_CIDS_JSON
    )
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/cid/.*/property/.*").respond(
        json=payloads.PUBCHEM_PROPERTIES_JSON
    )
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/cid/.*/description/JSON").respond(
        json=payloads.PUBCHEM_DESCRIPTION_JSON
    )

    result = await PubChemSource(client, settings).search("aspirin", 5)

    params = cids.calls.last.request.url.params
    assert params["tool"] == "dockshift" and params["email"] == "test@example.com"

    assert result.total == 2
    first, second = result.documents
    assert [first.id, second.id] == ["pubchem:2244", "pubchem:2662"]  # PubChem CID order
    assert first.title == "Aspirin"
    assert first.abstract == "Aspirin is a non-steroidal anti-inflammatory drug."
    assert first.authors == []
    assert first.published_date is None
    assert first.venue == "PubChem"
    assert first.url == "https://pubchem.ncbi.nlm.nih.gov/compound/2244"
    assert first.identifiers == {"cid": "2244", "inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"}
    assert first.metadata["molecular_formula"] == "C9H8O4"
    assert first.metadata["molecular_weight"] == "180.16"
    assert first.metadata["iupac_name"] == "2-acetyloxybenzoic acid"
    assert first.full_text_available is True
    assert second.title == "Celecoxib"


@respx.mock
async def test_pubchem_unknown_name_returns_no_results(client, settings):
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/name/.*/cids/JSON").respond(
        status_code=404, json={"Fault": {"Code": "PUGREST.NotFound"}}
    )
    props = respx.get(url__regex=rf"{PUG_REST_BASE}/compound/cid/.*/property/.*")
    result = await PubChemSource(client, settings).search("zzznotacompound", 5)
    assert result.total == 0 and result.documents == []
    assert not props.called


async def test_pubchem_full_text_reuses_document_description(client, settings):
    doc = Document(
        id="pubchem:2244",
        source=Source.PUBCHEM,
        title="Aspirin",
        abstract="Aspirin is a non-steroidal anti-inflammatory drug.",
    )
    # No HTTP mocks registered: a reused abstract must not trigger a network call.
    text = await PubChemSource(client, settings).fetch_full_text(doc.native_id, doc)
    assert text == "Aspirin is a non-steroidal anti-inflammatory drug."


@respx.mock
async def test_pubchem_full_text_fetches_description_when_absent(client, settings):
    respx.get(url__regex=rf"{PUG_REST_BASE}/compound/cid/.*/description/JSON").respond(
        json=payloads.PUBCHEM_DESCRIPTION_JSON
    )
    text = await PubChemSource(client, settings).fetch_full_text("2662")
    assert text == "Celecoxib is a COX-2 selective nonsteroidal anti-inflammatory drug."
