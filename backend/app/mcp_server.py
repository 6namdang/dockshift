"""MCP server exposing literature, hTERT QSAR, and structural tools to agents.

Run standalone over stdio (for Claude Desktop / Claude Code / any MCP client):

    uv run python -m app.mcp_server

Or over separately enabled and Bearer-authenticated Streamable HTTP:

    MCP_HTTP_ENABLED=true MCP_HTTP_TOKEN=... \\
      uv run python -m app.mcp_server --http --port 8001

The FastAPI app mounts this server at ``/mcp`` only when the same HTTP MCP settings are valid.
Stdio remains available without an HTTP token.
"""

from __future__ import annotations

import argparse
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field, SecretStr
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.agent import (
    DEFAULT_SHORTLIST,
    PipelineService,
    ShortlistResponse,
    Target,
)
from app.config import Settings, get_settings
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
from app.structural import (
    AlphaFold3Request,
    DockingRequest,
    FPocketRequest,
    GromacsRequest,
    LigandPreparationRequest,
    PocketComparisonRequest,
    PocketPlanRequest,
    ReceptorPreparationRequest,
    StructuralService,
    StructuralWorkflowRequest,
    TMAlignRequest,
)
from app.structural.models import FileInput, PocketBoxRequest

INSTRUCTIONS = """\
Tools for drug-discovery research: scientific literature search, target screening,
hTERT telomerase QSAR, and an approval-gated structural discovery workflow.

Workflow: call `search_literature` first. Results across PubMed, bioRxiv, ChemRxiv,
patents and PubChem (compounds) come back merged and ranked by `confidence` (0-1,
lexical match of the query against title + abstract). Full text is attached
automatically only for highly relevant, open-access hits. Call `get_full_text` with a
result `id` when you need the full paper/patent for a hit that didn't get it. Always
cite the `url` or `doi` of the documents you use.

hTERT QSAR: `list_targets` then `shortlist_inhibitors` scores a target's candidate
molecules and ranks them by predicted potency. `predict_htert_activity` scores any
compounds given by name or SMILES, `profile_compound` reports drug-likeness, and
`search_htert_dataset` finds experimentally measured compounds. Predicted potency is a
model estimate with roughly half-a-log-unit error: report it as a prediction, never as a
measurement, say when a compound falls outside the applicability domain (`domain: "out"`),
and prefer `measured_pic50` whenever it is present. Call `get_htert_model_info` for the
model's performance and citation before making strong claims about its output.

Target screening: `shortlist_inhibitors` ranks the fixed candidate set without claiming that
literature review is complete. `find_candidates_in_literature` grounds proposals in retrieved
abstracts before QSAR ranking and requires a configured OpenAI-compatible endpoint. For a
structural handoff, use the canonical `prediction.smiles` for at most six selected ligands and
preserve each entry's QSAR profile and citations as metadata; complete the structural workflow's
literature checkpoint separately after scientific review.

Structural discovery: call `structural_preflight` before jobs. Structural tools are thin
adapters around configured TM-align, official AlphaFold 3, fpocket, Open Babel, AutoDock
Vina and local GROMACS executables; none of those engines or AF3 assets are bundled. Before
calling the workflow, use individual alignment, fpocket, pocket-comparison, and pocket-box
tools, then create an immutable pocket plan. Present its exact digest, artifact, pocket IDs,
and boxes for scientist approval. The workflow accepts only approval bound to that proposal and
does not rerun AF3, TM-align, or fpocket. Run AF3 standalone first when needed and plan with its
explicit `top_ranked_structure`. Large inline MSAs/templates must be omitted for AF3 pipeline
generation until a future file-backed interface exists. Vina values are docking scores, not
measured affinities. GROMACS requires a scientist-approved, already parameterized and solvated
system bundle; its energy and convergence analysis happens downstream after the run. MCP stdio
is a local process transport and needs no HTTP token. HTTP MCP is separately disabled by default
and requires `MCP_HTTP_TOKEN` when enabled; the structural REST token is never reused implicitly.
"""


@dataclass
class Services:
    """What the tools need, built once for the server's lifetime."""

    literature: LiteratureSearchService
    qsar: QsarService
    pipeline: PipelineService
    structural: StructuralService


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
            structural=StructuralService(settings),
        )


mcp = MCPServer(
    name="dockshift",
    title="Dockshift literature, hTERT QSAR & structural discovery",
    instructions=INSTRUCTIONS,
    version="0.2.0",
    lifespan=_lifespan,
)

_MCP_HTTP_BODY_LIMIT = 4 * 1024 * 1024


class MCPHTTPBearerAuth:
    """Constant-time static Bearer authentication for the entire HTTP MCP app."""

    def __init__(self, app: ASGIApp, token: SecretStr) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        scheme, separator, supplied = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not supplied:
            response = JSONResponse(
                {"code": "mcp_auth_required", "message": "A Bearer token is required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        if not secrets.compare_digest(supplied, self.token.get_secret_value()):
            response = JSONResponse(
                {"code": "mcp_auth_invalid", "message": "The Bearer token is invalid."},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_mcp_http_app(settings: Settings | None = None) -> ASGIApp:
    """Build the separately enabled and authenticated Streamable HTTP MCP app."""
    configured = settings or get_settings()
    if not configured.mcp_http_enabled:
        raise RuntimeError("HTTP MCP is disabled; set MCP_HTTP_ENABLED=true to enable it.")
    token = configured.mcp_http_token
    if token is None or not token.get_secret_value():
        raise RuntimeError(
            "HTTP MCP is enabled without MCP_HTTP_TOKEN; refusing to expose the endpoint."
        )
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        max_request_body_size=_MCP_HTTP_BODY_LIMIT,
    )
    return MCPHTTPBearerAuth(app, token)


def _services(ctx: Context) -> Services:
    return ctx.request_context.lifespan_context


def _service(ctx: Context) -> LiteratureSearchService:
    return _services(ctx).literature


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


@mcp.tool(title="Structural engine preflight")
async def structural_preflight(ctx: Context) -> dict[str, Any]:
    """Report executable and official AlphaFold 3 asset availability without running a job."""
    result = await _services(ctx).structural.capabilities()
    return result.model_dump(mode="json")


@mcp.tool(title="Align protein structures with TM-align")
async def run_tmalign(
    structure_a: Annotated[
        str,
        Field(min_length=1, description="Structure A under the structural input/artifact root."),
    ],
    structure_b: Annotated[
        str,
        Field(min_length=1, description="Structure B under the structural input/artifact root."),
    ],
    ctx: Context,
) -> dict[str, Any]:
    """Run configured TM-align and return alignment metrics plus the A-to-B transform."""
    request = TMAlignRequest(
        structure_a=FileInput(path=structure_a), structure_b=FileInput(path=structure_b)
    )
    result = await _services(ctx).structural.tmalign(request)
    return result.model_dump(mode="json")


@mcp.tool(title="Run official AlphaFold 3")
async def run_alphafold3(request: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Validate official dialect-v1 input and run the configured official local AF3 script."""
    result = await _services(ctx).structural.alphafold3(AlphaFold3Request.model_validate(request))
    return result.model_dump(mode="json")


@mcp.tool(title="Prepare docking ligand")
async def prepare_structural_ligand(
    name: Annotated[str, Field(min_length=1, max_length=80)],
    ctx: Context,
    smiles: Annotated[str | None, Field(description="Ligand SMILES.")] = None,
    sdf_path: Annotated[
        str | None, Field(description="SDF path under the structural input/artifact root.")
    ] = None,
    random_seed: Annotated[int, Field(ge=0, le=2_147_483_647)] = 61453,
    optimize: bool = True,
) -> dict[str, Any]:
    """Generate a 3D RDKit conformer and Open Babel PDBQT from SMILES or SDF."""
    request = LigandPreparationRequest(
        name=name,
        smiles=smiles,
        sdf=FileInput(path=sdf_path) if sdf_path else None,
        random_seed=random_seed,
        optimize=optimize,
    )
    result = await _services(ctx).structural.prepare_ligand(request)
    return result.model_dump(mode="json")


@mcp.tool(title="Prepare rigid docking receptor")
async def prepare_structural_receptor(
    structure_path: Annotated[
        str,
        Field(
            min_length=1,
            description="PDB/mmCIF path under the structural input/artifact root.",
        ),
    ],
    ctx: Context,
    remove_waters: bool = True,
    remove_heterogens: bool = False,
    remove_alternate_locations: bool = True,
) -> dict[str, Any]:
    """Conservatively clean a receptor and create rigid-receptor PDBQT with Open Babel."""
    request = ReceptorPreparationRequest(
        structure=FileInput(path=structure_path),
        remove_waters=remove_waters,
        remove_heterogens=remove_heterogens,
        remove_alternate_locations=remove_alternate_locations,
    )
    result = await _services(ctx).structural.prepare_receptor(request)
    return result.model_dump(mode="json")


@mcp.tool(title="Detect pockets with fpocket")
async def run_fpocket(
    structure_path: Annotated[
        str,
        Field(min_length=1, description="Protein path under the structural input/artifact root."),
    ],
    ctx: Context,
) -> dict[str, Any]:
    """Run configured fpocket and return pocket geometry, residues, and reported scores."""
    result = await _services(ctx).structural.fpocket(
        FPocketRequest(structure=FileInput(path=structure_path))
    )
    return result.model_dump(mode="json")


@mcp.tool(title="Compare superimposed pockets")
async def compare_structural_pockets(request: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Compare two pockets with a supplied TM-align transform using deterministic geometry."""
    result = await _services(ctx).structural.compare_pockets(
        PocketComparisonRequest.model_validate(request)
    )
    return result.model_dump(mode="json")


@mcp.tool(title="Propose a docking box from one pocket")
async def generate_structural_pocket_box(request: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Generate a box proposal; oversized boxes fail and require explicit reviewed coordinates."""
    result = await _services(ctx).structural.pocket_box(PocketBoxRequest.model_validate(request))
    return result.model_dump(mode="json")


@mcp.tool(title="Create immutable structural pocket plan")
async def create_structural_pocket_plan(request: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Hash exact structures, transform, selected pockets and boxes into an approval proposal."""
    result = await _services(ctx).structural.create_pocket_plan(
        PocketPlanRequest.model_validate(request)
    )
    return result.model_dump(mode="json")


@mcp.tool(title="Dock with AutoDock Vina")
async def run_vina_docking(request: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Run configured Vina with prepared PDBQT files and an explicit bounded search box."""
    result = await _services(ctx).structural.dock(DockingRequest.model_validate(request))
    return result.model_dump(mode="json")


@mcp.tool(title="Run structural discovery workflow")
async def run_structural_workflow(request: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Run dual-target docking from an exact digest-bound pocket proposal."""
    result = await _services(ctx).structural.run_workflow(
        StructuralWorkflowRequest.model_validate(request)
    )
    return result.model_dump(mode="json")


@mcp.tool(title="Run staged GROMACS protocol")
async def run_gromacs(request: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Run local em/nvt/npt/md; review energy and convergence after the returned result."""
    result = await _services(ctx).structural.run_gromacs(GromacsRequest.model_validate(request))
    return result.model_dump(mode="json")


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

    Searches PubMed, bioRxiv, ChemRxiv and patents for inhibitors of the target, has an LLM
    propose compounds grounded in those abstracts, then keeps only proposals that resolve to
    a real structure in PubChem and pass a small-molecule check (molecular weight, rotatable
    bonds, heavy atoms). Survivors are scored with the target's QSAR model and ranked.

    `dropped` lists what was rejected and why, and each entry carries the papers it came
    from. Proposals are a reading of the literature and scores are model estimates: neither
    is evidence of activity. Requires OPENAI_API_KEY.
    """
    return await _services(ctx).pipeline.literature_shortlist(target_id, count, query)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dockshift MCP server")
    parser.add_argument(
        "--http", action="store_true", help="Serve Streamable HTTP instead of stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    settings = get_settings()  # fail fast on invalid configuration
    if args.http:
        import uvicorn

        uvicorn.run(create_mcp_http_app(settings), host=args.host, port=args.port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
