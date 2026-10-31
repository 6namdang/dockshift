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
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from app.agent import (
    DEFAULT_SHORTLIST,
    PipelineService,
    ShortlistResponse,
    Target,
)
from app.config import get_settings
from app.literature import (
    FullTextMode,
    FullTextResult,
    LiteratureSearchService,
    SearchRequest,
    SearchResponse,
    Source,
)
from app.literature.http import build_http_client
from app.qsar import ActivityResponse, DatasetSearchResult, ProfileResponse, QsarService

INSTRUCTIONS = """\
Tools for drug-discovery research: scientific literature search, plus an hTERT
telomerase QSAR model.

Workflow: call `search_literature` first. Results across PubMed, bioRxiv, ChemRxiv,
and PubChem (compounds) come back merged and ranked by `confidence` (0-1,
lexical match of the query against title + abstract). Full text is attached
automatically only for highly relevant, open-access hits. Call `get_full_text` with a
result `id` when you need the full paper for a hit that didn't get it. Always
cite the `url` or `doi` of the documents you use.

hTERT QSAR: `list_targets` then `shortlist_inhibitors` scores a target's candidate
molecules and ranks them by predicted potency. `predict_htert_activity` scores any
compounds given by name or SMILES, `profile_compound` reports drug-likeness, and
`search_htert_dataset` finds experimentally measured compounds. Predicted potency is a
model estimate with roughly half-a-log-unit error: report it as a prediction, never as a
measurement, say when a compound falls outside the applicability domain (`domain: "out"`),
and prefer `measured_pic50` whenever it is present. Call `get_htert_model_info` for the
model's performance and citation before making strong claims about its output.
"""


@dataclass
class Services:
    """What the tools need, built once for the server's lifetime."""

    literature: LiteratureSearchService
    qsar: QsarService
    pipeline: PipelineService


@asynccontextmanager
async def _lifespan(_server: MCPServer) -> AsyncIterator[Services]:
    settings = get_settings()
    async with build_http_client(settings) as client:
        literature = LiteratureSearchService(client, settings)
        qsar = QsarService(client, settings)
        yield Services(
            literature=literature,
            qsar=qsar,
            pipeline=PipelineService(client, literature, qsar, settings),
        )


mcp = MCPServer(
    name="dockshift",
    title="Dockshift literature search & hTERT QSAR",
    instructions=INSTRUCTIONS,
    version="0.2.0",
    lifespan=_lifespan,
)


def _services(ctx: Context) -> Services:
    return ctx.request_context.lifespan_context


def _service(ctx: Context) -> LiteratureSearchService:
    return _services(ctx).literature


@mcp.tool(title="Search the literature")
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
            description=("Sources to search. Default: all (pubmed, biorxiv, chemrxiv, pubchem).")
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
    """Search PubMed, bioRxiv, ChemRxiv and PubChem in one call.

    Returns hits merged across sources, sorted by `confidence` (0-1). Each hit has title,
    authors (empty for PubChem compounds), abstract, date, venue,
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
                "e.g. 'pubmed:38012345' or 'biorxiv:PPR421180'."
            )
        ),
    ],
    ctx: Context,
) -> FullTextResult:
    """Fetch the full text of one document: open-access papers via Europe PMC.
    Long texts are truncated. Use sparingly: only for
    documents that look highly relevant, since full texts are large."""
    return await _service(ctx).get_full_text(document_id)


Compounds = Annotated[
    list[str],
    Field(
        description=(
            "Compounds as names or SMILES strings, e.g. ['quercetin', 'CCO']. Names are "
            "resolved through PubChem. Up to 50 per call."
        ),
        min_length=1,
        max_length=50,
    ),
]


@mcp.tool(title="Predict hTERT inhibition potency")
async def predict_htert_activity(compounds: Compounds, ctx: Context) -> ActivityResponse:
    """Predict hTERT telomerase-inhibition potency (pIC50) for compounds.

    Uses the published QSAR model of Iraqui & Dang (2026): XGBoost on Morgan fingerprints
    plus RDKit descriptors, trained on 616 ChEMBL compounds. For each compound it returns
    `predicted_pic50` and `predicted_ic50_nm`, the similarity to the nearest training
    compound (`max_tanimoto`), and whether that puts it inside the model's applicability
    domain. `measured_pic50` is filled in when the compound has real ChEMBL data, and
    `in_training_set` marks compounds the model was fitted on (their predictions are
    optimistic). Held-out R^2 is about 0.53, so treat values as triage, not measurement.
    """
    return await _services(ctx).qsar.predict_activity(compounds)


@mcp.tool(title="Profile drug-likeness")
async def profile_compound(compounds: Compounds, ctx: Context) -> ProfileResponse:
    """Compute physicochemical and drug-likeness properties for compounds.

    Returns molecular weight, cLogP, hydrogen-bond donors/acceptors, TPSA, rotatable
    bonds, aromatic rings, QED, Lipinski rule-of-five violations and Veber pass/fail.
    All computed locally with RDKit, with no model involved, so these are deterministic
    calculated properties rather than predictions.
    """
    return await _services(ctx).qsar.profile(compounds)


@mcp.tool(title="Search measured hTERT compounds")
async def search_htert_dataset(
    compound: Annotated[
        str, Field(description="A compound name or SMILES string to look for.", min_length=1)
    ],
    ctx: Context,
    limit: Annotated[
        int, Field(ge=1, le=25, description="How many similar compounds to return (default 5).")
    ] = 5,
) -> DatasetSearchResult:
    """Find experimentally measured hTERT compounds in the curated ChEMBL dataset.

    Returns `exact_match` when the query structure is itself in the 616-compound dataset,
    plus the nearest measured compounds by Tanimoto similarity with their experimental
    pIC50 values. Useful for grounding a prediction in real data, and for judging whether
    a compound sits in a well-measured region of chemical space. The dataset holds
    structures and potencies only: compound names are dropped during curation, so results
    are identified by SMILES.
    """
    return await _services(ctx).qsar.search_dataset(compound, limit)


@mcp.tool(title="hTERT model provenance")
async def get_htert_model_info(ctx: Context) -> dict[str, Any]:
    """Report how the hTERT QSAR model was built and how well it performs.

    Returns the training data and its potency range, the algorithm and hyperparameters,
    the feature representation, held-out and cross-validated performance, the
    applicability-domain rule and threshold, the algorithm benchmark, top feature
    importances, known caveats, and the paper citation and DOI. Use this to caveat or cite
    predictions accurately.
    """
    return await _services(ctx).qsar.model_info()


@mcp.tool(title="List screenable targets")
async def list_targets(ctx: Context) -> list[Target]:
    """List protein targets that can be screened, and whether each has a QSAR model.

    Only targets with `qsar_available` can have candidates scored, because scoring needs
    a model trained on that target's measured compounds.
    """
    return _services(ctx).pipeline.targets()


@mcp.tool(title="Shortlist inhibitor candidates")
async def shortlist_inhibitors(
    target_id: Annotated[
        str, Field(description="Target id from list_targets, e.g. 'htert'.", min_length=1)
    ],
    ctx: Context,
    count: Annotated[
        int, Field(ge=1, le=12, description="How many candidates to shortlist (default 6).")
    ] = DEFAULT_SHORTLIST,
) -> ShortlistResponse:
    """Score a target's candidate molecules with its QSAR model and rank them.

    Returns every candidate ranked by predicted potency (pIC50), with `selected` marking
    the top `count`. Each entry carries its predicted and, where ChEMBL has one, measured
    potency, its applicability-domain status and its drug-likeness profile.

    Scores are model estimates with roughly half a log unit of error: use them to rank
    and triage, and say so rather than presenting them as measurements.
    """
    return await _services(ctx).pipeline.shortlist(target_id, count)


@mcp.tool(title="Find inhibitor candidates in the literature")
async def find_candidates_in_literature(
    target_id: Annotated[
        str, Field(description="Target id from list_targets, e.g. 'htert'.", min_length=1)
    ],
    ctx: Context,
    count: Annotated[
        int, Field(ge=1, le=12, description="How many molecules to shortlist (default 6).")
    ] = DEFAULT_SHORTLIST,
    query: Annotated[
        str | None,
        Field(description="Literature query to use; defaults to the target's own query."),
    ] = None,
) -> ShortlistResponse:
    """Search the literature for a target, pull candidate small molecules out of it, and score them.

    Searches PubMed, bioRxiv and ChemRxiv for inhibitors of the target, has an LLM
    propose compounds grounded in those abstracts, then keeps only proposals that resolve to
    a real structure in PubChem and pass a small-molecule check (molecular weight, rotatable
    bonds, heavy atoms). Survivors are scored with the target's QSAR model and ranked.

    `dropped` lists what was rejected and why, and each entry carries the papers it came
    from. Proposals are a reading of the literature and scores are model estimates: neither
    is evidence of activity. Requires OPENAI_API_KEY.
    """
    return await _services(ctx).pipeline.literature_shortlist(target_id, count, query)


@mcp.tool(title="Screen a compound library")
async def screen_compound_library(
    target_id: Annotated[
        str, Field(description="Target id from list_targets, e.g. 'htert'.", min_length=1)
    ],
    query: Annotated[
        str,
        Field(
            description="A compound already known to work against the target, as a name or "
            "SMILES, e.g. 'BIBR1532'.",
            min_length=1,
        ),
    ],
    ctx: Context,
    count: Annotated[
        int, Field(ge=1, le=12, description="How many molecules to return (default 6).")
    ] = DEFAULT_SHORTLIST,
) -> ShortlistResponse:
    """Find molecules in a compound library that resemble a known active, then score them.

    Ranks 10,000 real ChEMBL compounds by structural similarity (Morgan fingerprint,
    Tanimoto) to the query, clusters the top of that ranking so the picks are distinct
    chemotypes rather than near-duplicates, then scores the picks with the target's QSAR
    model and ranks them by predicted potency.

    Every hit is an existing library compound, so unlike the literature route nothing can
    be invented. Scores remain model estimates, not measurements. No API key needed.
    """
    return await _services(ctx).pipeline.library_screen(target_id, query, count)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dockshift MCP server")
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
