# Connected research path and preservation audit

Compared against local `origin/main` (`39a406cdf21cbb306149fa0c5fc0a78cb4d97510`).
The existing integration commit `5e4033e` is retained. This record accompanies the
connected-application checkpoint.
Only `dockshift-integration` was modified; no main-branch changes, push or merge.

## Original team files modified, and why

This list includes the earlier integration commit as well as current changes.
All other implementation files belong to the added integration package/view/tests.

| Original file | Necessary connection or supporting change |
|---|---|
| `backend/app/main.py` | Register added agent routes/services and drain managed runs before shared HTTP resources close. |
| `backend/app/config.py` | Add opt-in execution gates, separate Nebius LLM credentials/model, artifact limits and polling settings. |
| `backend/app/nebius/client.py` | Retain discovered input schemas; opt-in handling of accepted/pending MCP envelopes, preserving existing caller defaults. |
| `frontend/src/App.tsx` | Add the agents tab/shortcut and pass only selected candidate identity to the integration view. |
| `frontend/src/components/NavigationSidebar.tsx` | Add one navigation entry and shortcut hint; retain all original navigation. |
| `frontend/src/dockshiftApi.ts` | Earlier commit's additive agent API types/functions; new managed-run client lives separately in `frontend/src/integration/researchApi.ts`. |
| `backend/pyproject.toml` | Declare JSON Schema validation and pytest; scoped lint allowances for imported source runtime. |
| `backend/uv.lock` | Lock the declared dependencies; existing scientific package pins retained. |
| `frontend/package.json` | Add the test command using existing dependencies. |
| `frontend/dist/index.html` | Point the existing FastAPI-served UI at its updated production assets. |
| `backend/.gitignore` | Ignore newly generated scientific run directories. |
| `backend/.env.example` | Document new optional settings without credentials; defaults deny scientific submission. |
| `README.md` | Link to the integration instructions. |
| `backend/.env` | Removed from Git tracking at the security checkpoint; the existing local file is preserved unchanged and remains ignored. |

The original QSAR, literature, structural, scientific computation, receptor and
pipeline implementations are unchanged. `ScreenView`, `LiteratureView`,
`MolecularViewer`, `CompareView`, `DiscoverView`, molecular inspection, research
notes, and `dockingService.ts` are unchanged. Original illustrative/demo displays
retain their existing labels and behavior. The new research client never uses
their sample scores, fallback papers or cached example predictions; it sends
only candidate identity and recomputes scientific outputs through the backend.
No scientific source files or historical result directories were deleted. The
checkpoint removes the credential-bearing `backend/.env` from tracking while
retaining its exact local bytes. Earlier Git history is unchanged and still
contains that previously tracked file; credential rotation/history cleanup is
separate from this local checkpoint.

## Exact user actions and execution

| React action | Backend endpoint | Result |
|---|---|---|
| Open Scientific Agents | `GET /api/v1/agents/capabilities` | Live scientific tool schemas, execution gates and Nebius LLM configuration/catalog status. |
| Start research run | `POST /api/v1/agents/research` | Returns HTTP 202 and a persisted run ID immediately; executes the native eight-worker runtime. |
| Automatic monitoring / Monitor-load | `GET /api/v1/agents/runs/{id}/progress` | Atomic snapshots of each worker; interrupted execution is blocked after restart, not replayed. |
| Automatic final result retrieval | `GET /api/v1/agents/runs/{id}` | Hash-checked report, independent science/review status, typed metrics, provenance and limitations. |
| Resume recorded operations | `POST /api/v1/agents/runs/{id}/resume` | New evidence run which polls recorded Nebius operation IDs; it does not resubmit those jobs. |
| Download verified scientific artifact | `GET /api/v1/agents/runs/{id}/artifacts/{filename}` | Authenticated exact bytes after report/manifest verification. |
| Download evidence report | Browser-generated JSON | Current authenticated report; no extra scientific execution. |

Existing `POST /api/v1/agents/runs` remains the synchronous compatibility endpoint.
All execution/progress/report/artifact endpoints use the original structural
REST Bearer gate. Existing QSAR, literature and structural routes keep their API
contracts, settings and authentication.

Candidate scope executes A1 (live human hTERT accession/gene/taxon verification
and optional existing literature search), A2 (existing structural capabilities
or reviewed alignment), A3 (existing QSAR/profiles plus chemical audit and Nebius
ADMET), and A7 (independent hash/completeness audit). All eight workers are invoked;
A4, A5a, A5b and A6 explicitly block when their reviewed inputs or execution
approval are missing. A3 depends on verified identity, not a structure: QSAR and
ADMET do not require a protein structure. The source tool-calling loop and
hash-verified evidence handoffs remain in use.

Nebius LLM reviews use the Token Factory `/models` and `/chat/completions`
interfaces with explicit credentials and selected catalog model. No local
Ollama or another inference provider is substituted. Without this configuration,
tools can run, but zero LLM workers are claimed and agent reviews remain blocked.
The source local-provider implementation is preserved as source provenance,
not selected by the connected research path.

## Actual live scientific and browser verification

On November 1, 2026, a single BIBR1532 molecule was submitted once to Nebius
`infer_admet_ai_native` through the FastAPI managed research endpoint.
Model: **ADMET-AI 2.0.1**; operation: **`op-3c5e1fac10a00bff`**.
The server reported successful computation, not a mocked result.

The runner used `get_operation`, `get_operation_result`,
`get_scientific_artifact` and `download_scientific_artifact`. It downloaded
**1,103 bytes** and verified their size and SHA-256:
`cbd7a785c8d754225059db516e6eab0784f87524f9d8b168271990e308d56f2a`.
The native artifact's molecule ID, input/canonical SMILES, success status,
endpoint finiteness, units/species and model version were validated before its
values entered the typed ledger. Native values were retained:

| Output | Observed model prediction | Native unit/species |
|---|---:|---|
| Dockshift hTERT QSAR | 5.83 | pIC50; prediction, not assay |
| ADMET hERG | 0.26131659746170044 | dimensionless classification score; human |
| ADMET AMES | 0.2498425990343094 | dimensionless classification score; salmonella typhimurium |
| ADMET aqueous solubility | -5.214654445648193 | log(mol/L); species unspecified (`-`) |

The first strict parser blocked the unfamiliar native identity field names.
After adapting to the observed schema, the same operation was resumed, not
resubmitted. Original evidence was preserved. A real headless Chrome test then
opened the original React app served by FastAPI, opened Scientific Agents,
loaded the verified result, clicked Resume, monitored all workers and downloaded
the artifact. Its byte hash matched the above. The original Screen view still
rendered and Chrome reported no page errors.

Browser-verified report: `agents-49cfb098b3af4439885e599fef6af6a6`.
API-verified predecessor: `agents-e5c4cb9049f4475daca1aa89c95f50f9`.
Evidence is retained locally under ignored `backend/.dockshift-agent-runs/`;
it is not shipped as application demo data. The browser test used disabled
submission gates and only resumed the already completed operation.

**Completed candidate screen is distinct from completed collective science.**
The candidate screen completed. The full run remains BLOCKED: structural
comparison, biologic design, complex prediction, docking and validated MD were
not completed. No expensive inference or simulation was run. Nebius LLM agent
reviews were not configured or live-tested; the live run reports zero LLM calls.
ADMET predictions do not establish human safety, hTERT binding or inhibition.
No applicability-domain/calibrated uncertainty estimate is provided by ADMET-AI.

## Final full browser Start-research test

A subsequent headless Chrome test clicked **Start research run** in the actual
React UI, using a temporary backend configuration that authorized only one-molecule
ADMET. It followed HTTP 202 through worker progress, native Nebius execution,
verified report display and exact artifact download. No API or scientific service
was mocked in this test.

- Run: `agents-2395140504af4992b31cadcbb7dcc8c7`
- Nebius operation: `op-a407d2c206991b91`
- Model: ADMET-AI `2.0.1`
- Artifact: 1,103 bytes; SHA-256
  `6af70fec1f5d588bfd905013cfeb663b1f76f463aec9b2e9406e8e7b4643541e`
- Candidate screen: **COMPLETED**; full collective workflow: **BLOCKED**.
- Browser page errors: **0**.

Two small single-molecule ADMET computations were submitted in total during this
work: the initial API test and this final browser Start test. All intermediate
resume checks reused the first operation without submitting inference again.
No expensive structural/design/MD jobs or LLM inference were executed, no result
was fabricated, and persistent submission settings remain disabled by default.

The final automated suite passes **42 backend tests and 7 frontend tests**.
Ruff, TypeScript, the production build and the frozen backend lockfile check pass.
The build retains existing dependency warnings concerning chunk size, 3dmol eval
and Vite's configuration loader; no team dependency or original component was
rewritten to suppress them.

## Regression and failure verification

Offline tests cover real local RDKit/QSAR execution and existing QSAR endpoints,
SVG depiction, measured-dataset lookup, target listing, health, literature API
shape, structural prerequisite/auth errors, old synchronous agent endpoints,
managed asynchronous API authentication/progress/downloads, native ADMET schema
validation, pending jobs, resume without resubmission, digest mismatch, private
artifact URLs, secret redaction and source decision/handoff contracts.
Nebius LLM wire-format tests use explicit doubles and do not count as live LLM
execution. Frontend tests cover original navigation/screen rendering, new API
paths/authentication, real-output rendering, blocked/full-scope distinctions and
absence of demo fallback in the research client.
