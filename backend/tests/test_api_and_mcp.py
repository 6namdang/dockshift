from __future__ import annotations

import pytest
import respx
from fastapi.testclient import TestClient
from mcp import Client

from app.api.deps import get_literature_service
from app.literature.models import FullTextResult, SearchRequest, SearchResponse
from app.main import create_app
from app.mcp_server import mcp
from tests.test_service import mock_all_sources


class FakeService:
    def __init__(self) -> None:
        self.requests: list[SearchRequest] = []

    async def search(self, req: SearchRequest) -> SearchResponse:
        self.requests.append(req)
        return SearchResponse(query=req.query, results=[], full_text_threshold=0.75)

    async def get_full_text(self, document_id: str) -> FullTextResult:
        return FullTextResult(id=document_id, available=False, message="fake")


@pytest.fixture
def api():
    app = create_app()
    fake = FakeService()
    app.dependency_overrides[get_literature_service] = lambda: fake
    with TestClient(app) as client:
        yield client, fake


def test_health(api):
    client, _ = api
    body = client.get("/health").json()
    assert body["status"] == "ok" and set(body["sources"]) == {
        "pubmed",
        "biorxiv",
        "chemrxiv",
        "patents",
    }


def test_search_endpoint_validates_and_forwards(api):
    client, fake = api
    ok = client.post(
        "/api/v1/literature/search",
        json={"query": "kras", "sources": ["pubmed", "pubmed"], "full_text": "never"},
    )
    assert ok.status_code == 200 and ok.json()["query"] == "kras"
    assert fake.requests[-1].sources == ["pubmed"]  # de-duplicated

    for bad in (
        {"query": ""},
        {"query": "   "},
        {"query": "x", "sources": ["nature"]},
        {"query": "x", "max_results_per_source": 500},
        {"query": "x", "year_from": 2025, "year_to": 2020},
    ):
        assert client.post("/api/v1/literature/search", json=bad).status_code == 422, bad


def test_full_text_endpoint_accepts_ids_with_slashes(api):
    client, _ = api
    response = client.get("/api/v1/literature/full-text/chemrxiv:10.26434/chemrxiv-2024-x8kvm")
    assert response.status_code == 200
    assert response.json()["id"] == "chemrxiv:10.26434/chemrxiv-2024-x8kvm"


async def test_mcp_lists_tools_with_descriptions():
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"search_literature", "get_full_text"}
    search = tools["search_literature"]
    assert "PubMed" in search.description
    props = search.input_schema["properties"]
    assert set(props) == {
        "query",
        "sources",
        "max_results_per_source",
        "year_from",
        "year_to",
        "full_text",
    }
    assert search.input_schema["required"] == ["query"]
    assert "ctx" not in props


@respx.mock
async def test_mcp_search_tool_end_to_end():
    mock_all_sources()
    async with Client(mcp) as client:
        result = await client.call_tool(
            "search_literature",
            {
                "query": "KRAS G12C covalent inhibitor",
                "sources": ["pubmed", "biorxiv"],
                "full_text": "never",
            },
        )
    assert not result.is_error
    ids = [r["id"] for r in result.structured_content["results"]]
    assert "pubmed:222" in ids and "biorxiv:PPR100" in ids


async def test_mcp_search_tool_rejects_bad_input():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "search_literature", {"query": "x", "year_from": 2025, "year_to": 2000}
        )
    assert result.is_error
