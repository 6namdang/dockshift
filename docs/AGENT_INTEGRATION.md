# Scientific agent integration

Implementation target: `dockshift-integration`, branch
`feature/nebius-agent-integration`, starting at `39a406c`.
`Agentic_System_Test` is a read-only source. No scientific artifacts or caches
are moved, replaced, or interpreted as new runs.

## Stages and verification

1. **Runtime and Nebius:** imported the existing native tool-calling loop,
   hash-verified handoffs, strict decisions, evidence contracts, append-only
   ledger, chemical validation, score-separation guards, and report exporter.
   `backend/app/integration/scienceclaw/SOURCE.json` records upstream file
   digests. Local demo cache access and scientific engines are replaced with
   Dockshift service bindings, so this checkout has no runtime dependency on
   the source repository. Remote schemas are discovered and validated before
   submission; arguments and schemas are recorded in immutable run receipts.
2. **API and React:** added `/api/v1/agents/capabilities`, authenticated
   `POST /api/v1/agents/runs`, and authenticated `GET /api/v1/agents/runs/{id}`.
   The existing React app has a Scientific Agents tab (shortcut 6), discovered
   schemas, reviewed JSON inputs, separate scientific/reviewer states, report
   retrieval, and JSON export. Existing views and services remain in place.
3. **Verification:** **25 backend tests and 3 frontend tests pass**. Ruff,
   TypeScript, the backend lockfile check and production build pass. Offline tests cover the eight-worker native loop with a
   scripted LLM provider, actual local RDKit/QSAR execution, schema validation,
   pending/failed/success responses, polling without submission, authentication,
   tamper detection, secret redaction, prerequisite-only models, and existing
   backend routes. Frontend tests cover authenticated API requests, rendering
   blocked evidence, and errors without demo fallback. TypeScript and production
   build pass. Read-only live Nebius discovery returned **69 tools with 69 input
   schemas** on November 1, 2026. No live inference, docking, folding, binder
   design, or MD was submitted. The scripted provider is not a live LLM test.

## Model and service bindings

| Worker | Existing service / discovered Nebius tools |
|---|---|
| A1 | Source-system identity contract; Dockshift LiteratureSearchService |
| A2 | Dockshift StructuralService TM-align; AlphaFold3, OpenFold2/3, ESMFold2 |
| A3 | Dockshift QsarService and profiles with source Vchem; GenMol, MolMIM, ADMET-AI |
| A4 | ProteinMPNN, RFdiffusion, Proteina Complexa, RFD4 Proteina, BoltzGen |
| A5a | Nebius DiffDock via the existing NebiusClient |
| A5b | Boltz-2, Protenix v2, AlphaFold3, OpenFold3 |
| A6 | Nebius GROMACS, AMBER, OpenMM and MD precheck |
| A7 | Deterministic ledger audit and optional structured local LLM challenge |

Discovery advertises availability, not successful model execution or deployment
entitlement. Inputs must match the server's current schema. A4 models are named
explicitly because live discovery confirmed them; an optional additional exact
binder-tool name can be configured through `AGENT_NEBIUS_BINDER_TOOL`.

## Configuration and use

From `backend/`, install with `uv sync --group dev` and start the existing
FastAPI app. Existing `NEBIUS_API_KEY` / `SCIENTIFIC_MODELS_API_KEY` and MCP URL
settings are reused. Nothing copies credentials to the frontend.

Agent execution and report access share the existing structural REST gate:
`STRUCTURAL_REST_ENABLED=true` and `STRUCTURAL_API_TOKEN`. Supply that token in
the React password field or as a Bearer header. Tokens remain in React memory.

`AGENT_COMPUTE_ENABLED=false` is the default. It blocks remote submissions and
local structural calculations, while permitting read-only discovery, existing
operation polling, and cheap local chemical/QSAR validation. Enable compute
only after approving scientific jobs and reviewing their inputs and budgets.
This implementation does not enable it or modify `backend/.env`.

The default UI request intentionally blocks on unverified target identity.
Supply an hTERT target with its verified accession, named accession source and
appropriate structure identity. Verification is explicitly caller-attested;
this adapter does not claim to independently verify UniProt or PDB identity.
A1 may additionally run the existing literature service for `literature_query`.

Each subsequent worker needs its upstream scientific results and reviewed
inputs. Supply `alignment` using the existing TMAlignRequest schema, or use
`jobs` keyed by `A2`, `A3`, `A4`, `A5a`, `A5b`, `A6`. Each job has `tool` and
`arguments` matching a discovered schema. Immutable input manifests must already
be uploaded to Nebius where the tool requires them; this adapter does not invent
structures, ligand parameters, manifests, or upload identifiers.

Set `use_local_llm: true` to use the source runtime's existing loopback-only
Ollama provider and an already installed tool-capable model, configured through
`OLLAMA_HOST` and `SCIENCECLAW_LLM_MODEL`. It never downloads models. With LLM
execution disabled, tool receipts are still produced and agent review remains
BLOCKED; deterministic execution does not count as autonomous LLM agency.

Runs live in `backend/.dockshift-agent-runs/agents-<uuid>/`, configurable with
`AGENT_ARTIFACT_ROOT`. Every run gets a new directory, exclusive-write receipts,
hash-chained scientific ledger, trace, handoffs, report and file manifest.
Report retrieval rechecks the file hashes. Old scientific results are untouched.
Run admission is serialized per API process; deploy one worker if global
serialization is required. No background task queue or automatic redesign is
introduced. A7 proposals are saved for scientist review without additional jobs.

## Durable operations and scientific scope

An accepted operation is **BLOCKED pending result**, with its operation ID in
its science receipt; it is not completed science. To collect an existing job,
use the same job `tool` and its `operation_id` in a subsequent reviewed run.
This polls `get_operation`, then `get_operation_result` only after terminal
success, and never resubmits that job. Reuse operation IDs for other already
submitted jobs as well. There is no automatic retry of scientific execution,
acknowledgement, cancellation, or deletion. Submission idempotency keys are
stable within each run/worker and saved before the remote call.

COMPLETED, BLOCKED and FAILED are orchestration outcomes. Scientific tool status
and LLM review status are shown separately. Errors and missing tools never
become zero-valued metrics. ADMET alone cannot complete molecule generation;
MD precheck alone cannot complete MD. Generated molecules require local
chemical validation. Supplied compounds use existing QSAR predictions and
profiles and are explicitly labelled as screening, not de novo generation.

Remote results retain model-native fields in their receipts. Generic remote
numbers are not promoted into typed scientific metrics: model-specific artifact
parsing, target/candidate correspondence, pocket equivalence, reference pose
validation, binder-interface validation, and MD convergence review remain
scientist responsibilities. A remotely completed model job does not establish
those acceptance criteria. The original acceptance report remains in the bundle
and may say NOT_RUN/BLOCKED even when a remote operation completed. Every
candidate remains EXPERIMENT_REQUIRED. No DiffDock confidence is converted into
a Vina energy or pIC50, and no confidence/energy composite is constructed.

## Reproduce verification

```sh
cd backend
uv run pytest tests -q
uv run ruff check app tests
uv lock --check
cd ../frontend
npm ci
npm test
npm run lint
npm run build -- --emptyOutDir false
```

The frontend requires a Node version supported by Vite 8 (Node 20.19+ or
22.12+). Validation used a temporary Node 22 runtime without changing global
Node 18. Existing Vite warnings concern the 3dmol dependency's eval use, bundle
size and the pre-existing configuration loader. Existing hashed production
assets are preserved alongside the new build.
