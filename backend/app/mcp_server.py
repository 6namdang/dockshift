"""MCP server exposing the literature-search tools to agents.

Run standalone over stdio (for Claude Desktop / Claude Code / any MCP client):

    uv run python -m app.mcp_server

Or over Streamable HTTP, standalone:

    uv run python -m app.mcp_server --http --port 8001      # -> http://127.0.0.1:8001/mcp

The FastAPI app also mounts this server at ``/mcp`` (see ``app.main``).
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from app.config import get_settings
from app.literature import (
    FullTextMode,
    FullTextResult,
    LiteratureSearchService,
    SearchRequest,
    SearchResponse,
    Source,
    literature_service,
)

INSTRUCTIONS = """\
Tools for searching scientific literature and patents for drug-discovery research.

Workflow: call `search_literature` first. Results across PubMed, bioRxiv, ChemRxiv,
patents and PubChem (compounds) come back merged and ranked by `confidence` (0-1,
lexical match of the query against title + abstract). Full text is attached
automatically only for highly relevant, open-access hits. Call `get_full_text` with a
result `id` when you need the full paper/patent for a hit that didn't get it. Always
cite the `url` or `doi` of the documents you use.
"""


@asynccontextmanager
async def _lifespan(_server: MCPServer) -> AsyncIterator[LiteratureSearchService]:
    async with literature_service() as service:
        yield service


mcp = MCPServer(
    name="dockshift-literature",
    title="Dockshift literature search",
    instructions=INSTRUCTIONS,
    version="0.1.0",
    lifespan=_lifespan,
)


def _service(ctx: Context) -> LiteratureSearchService:
    return ctx.request_context.lifespan_context


@mcp.tool(title="Search literature & patents")
async def search_literature(
    query: Annotated[
        str,
        Field(
            description=(
                "Keywords to search for, e.g. 'KRAS G12C covalent inhibitor docking'. "
                "Plain keywords work best across all sources; quotes for exact phrases are OK."
            ),
            min_length=1,
            max_length=1000,
        ),
    ],
    ctx: Context,
    sources: Annotated[
        list[Source] | None,
        Field(
            description=(
                "Sources to search. Default: all (pubmed, biorxiv, chemrxiv, patents, pubchem)."
            )
        ),
    ] = None,
    max_results_per_source: Annotated[
        int, Field(ge=1, le=50, description="Max hits returned per source (default 10).")
    ] = 10,
    year_from: Annotated[
        int | None, Field(ge=1800, le=2100, description="Earliest publication year.")
    ] = None,
    year_to: Annotated[
        int | None, Field(ge=1800, le=2100, description="Latest publication year.")
    ] = None,
    full_text: Annotated[
        FullTextMode,
        Field(
            description=(
                "'auto' (default): attach full text to the few hits whose confidence is above the "
                "configured threshold and that are open access. 'never': metadata + abstracts only."
            )
        ),
    ] = FullTextMode.AUTO,
) -> SearchResponse:
    """Search PubMed, bioRxiv, ChemRxiv, patents (Lens.org) and PubChem in one call.

    Returns hits merged across sources, sorted by `confidence` (0-1). Each hit has title,
    authors (inventors for patents; empty for PubChem compounds), abstract, date, venue,
    DOI/URL and an `id` usable with
    `get_full_text`. Sources that fail or are not configured are listed in `errors`; the
    other sources' results are still returned.
    """
    request = SearchRequest(
        query=query,
        sources=sources or list(Source),
        max_results_per_source=max_results_per_source,
        year_from=year_from,
        year_to=year_to,
        full_text=full_text,
    )
    return await _service(ctx).search(request)


@mcp.tool(title="Get full text")
async def get_full_text(
    document_id: Annotated[
        str,
        Field(
            description=(
                "A result `id` from search_literature, "
                "e.g. 'pubmed:38012345' or 'patents:012-345-678-901-23X'."
            )
        ),
    ],
    ctx: Context,
) -> FullTextResult:
    """Fetch the full text of one document: open-access papers via Europe PMC, patents as
    claims + description via Lens.org. Long texts are truncated. Use sparingly: only for
    documents that look highly relevant, since full texts are large."""
    return await _service(ctx).get_full_text(document_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dockshift literature MCP server")
    parser.add_argument(
        "--http", action="store_true", help="Serve Streamable HTTP instead of stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    get_settings()  # fail fast on invalid configuration
    if args.http:
        mcp.run("streamable-http", host=args.host, port=args.port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
