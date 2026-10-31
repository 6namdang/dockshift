"""Smoke tests against the real APIs. Not run by default:

uv run pytest -m live
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.literature import FullTextMode, SearchRequest, Source, literature_service

pytestmark = pytest.mark.live


@pytest.mark.parametrize("source", [Source.PUBMED, Source.BIORXIV, Source.CHEMRXIV])
async def test_keyless_sources_return_results(source):
    async with literature_service() as service:
        response = await service.search(
            SearchRequest(
                query="molecular docking kinase",
                sources=[source],
                max_results_per_source=3,
                full_text=FullTextMode.NEVER,
            )
        )
    assert response.errors == []
    assert response.results and all(d.source == source for d in response.results)
    assert all(d.title and d.url for d in response.results)


async def test_pubchem_returns_compounds():
    async with literature_service() as service:
        response = await service.search(
            SearchRequest(
                query="aspirin",
                sources=[Source.PUBCHEM],
                max_results_per_source=3,
                full_text=FullTextMode.NEVER,
            )
        )
    assert response.errors == []
    assert response.results and all(d.source == Source.PUBCHEM for d in response.results)
    assert all(d.title and d.url for d in response.results)
    assert all(d.identifiers.get("cid") for d in response.results)


@pytest.mark.skipif(not get_settings().lens_api_token, reason="LENS_API_TOKEN not set")
async def test_patents_return_results():
    async with literature_service() as service:
        response = await service.search(
            SearchRequest(
                query="KRAS inhibitor", sources=[Source.PATENTS], max_results_per_source=3
            )
        )
    assert response.errors == [] and response.results


async def test_open_access_preprint_full_text():
    async with literature_service() as service:
        result = await service.get_full_text("biorxiv:PPR1213137")
    assert result.available and len(result.full_text) > 1000
