# Developer handoff

Work on `feature/nebius-agent-integration`. Keep `main` unchanged. No folding,
design, docking, MD, or paid LLM jobs were submitted during this implementation.

## Architecture and working paths

The existing React app and FastAPI services remain in place. The Scientific
Agents screen adds candidate research and collective protocol controls. New
adapters under `backend/app/integration/` reuse Dockshift QSAR, literature,
structural services and the existing authenticated Nebius MCP client. The
imported eight-worker runtime executes A1, A2, A3, A4, A5a, A5b, A6 and A7.
Typed artifact envelopes, SHA-256 checks, immutable run directories and the
append-only evidence ledger connect stages. Claude is the default reasoning provider; explicit legacy Token Factory requests
remain supported. See [Claude setup](CLAUDE_REASONING.md). Deterministic tools
are explicitly distinguished from LLM agency.

Frontend actions map to:

| Action | Backend endpoint |
|---|---|
| Check collective prerequisites | `POST /api/v1/agents/preflight` (discovery only) |
| Start candidate/collective run | `POST /api/v1/agents/research` |
| Monitor individual agents | `GET /api/v1/agents/runs/{id}/progress` |
| Inspect final evidence | `GET /api/v1/agents/runs/{id}` |
| Resume recorded operations | `POST /api/v1/agents/runs/{id}/resume` |
| Download verified artifacts | `GET /api/v1/agents/runs/{id}/artifacts/{name}` |

Collective resume reuses sealed successful steps and only polls recorded
operations. New stages require a separately reviewed continuation. Source runs
and input hashes must match; no existing artifacts are overwritten.

## Readiness and blockers

Claude integration update: the bounded eight-agent browser demonstration completed
real Claude reasoning for all workers, with scientific computation disabled. See
[the demo report](BOUNDED_WEBSITE_DEMO.md) and [Claude setup](CLAUDE_REASONING.md).

| Component | Verified here | Remaining requirement |
|---|---|---|
| React/FastAPI, existing QSAR and service regressions | Backend/API tests; frontend tests, TypeScript, build | Normal deployment/configuration |
| Eight-worker orchestration, both branches, typed handoffs, budgets, resume | Explicitly synthetic model-output fixtures and integrity tests | Approved live scientific qualification |
| A1 identity and literature | Existing services; offline API/orchestration checks | Network access; literature source outages remain explicit |
| A2 structure import/prediction | Real hTERT preparation preserved; folding format/identity/confidence fixture tests | Reviewed construct; optional Gemmi for mmCIF; live layouts |
| A3 GenMol/MolMIM → Dockshift QSAR/profiles | Chemistry, native counts and typed handoffs tested | Authorized model execution; predictions are not assays |
| A4 backbone/sequence design | ProteinMPNN and batch-design validator fixtures | Reviewed exposed epitope/scaffold, exact chain mapping and binder length; batch qualification |
| A5a DiffDock | Real 9Q14/55C inputs, request schema and reference-QC validator | Missing-region/protonation review; actual redocking must pass ≤2 Å unaligned RMSD before candidate docking |
| A5b complex prediction | Native identity/interface/confidence fixture tests | Actual designed binder and supported native output layout; no binding claim |
| A6 MD | Protocol schemas; input/bundle admission, energy parsers and artifact transport tested | Repaired assembly, real parameters/topology/solvation, optional native tools and trajectory parser; engine qualification and convergence review |
| A7 challenger/report | Ledger/artifact integrity and completeness tests | Scientific signoff and experiments; no automatic efficacy certification |
| Nebius Scientific AI | Authenticated read-only discovery and non-billable preflight | Tool discovery does not establish execution qualification |
| Token Factory | Interface, missing-credential and call-budget checks | Credentials/model access confirmation and separate inference approval |

Unknown native output layouts stay **BLOCKED**. Invalid outputs or explicit
native execution failures become **FAILED**. Accepted jobs remain pending until
results exist. Current provider metadata reports several batch models awaiting
exact-release qualification; see [inventory](NEBIUS_CONTRACT_INVENTORY.json).
No model-specific fixture is a live scientific result.

The deposited hTERT chain has 181 unobserved internal residues. The optional
local system builder refuses to invent long loops. Its AmberTools/OpenMM route,
ParmEd conversion, native upload handling, Gemmi and MDTraj parsing still require
installation and native qualification in a separate scientific environment.
Ordinary startup does not require those optional packages. No MD-ready hTERT
system or ligand force-field parameters were generated or validated here.

## Run locally

Prerequisites: Git, Python 3.11+ with `uv`, Node **22.12+** and npm. Node 18 cannot
build the current Vite toolchain. Do not overwrite an existing `.env`.

```bash
cd ~/dockshift-integration
git switch feature/nebius-agent-integration
cd backend
uv sync --frozen
[ -e .env ] || cp .env.example .env
cd ../frontend
npm ci
npm run build
cd ../backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/ui/** (React),
**http://127.0.0.1:8000/docs** (API), or
**http://127.0.0.1:8000/health**.

For React development, leave that backend running and use a second terminal:

```bash
cd ~/dockshift-integration/frontend
npm run dev
```

Open **http://localhost:3000/ui/**. Vite proxies `/api` and `/health` to port 8000.

The website and existing local QSAR paths can start without remote credentials.
To use authenticated agent endpoints, privately configure `backend/.env`:
`STRUCTURAL_REST_ENABLED=true` and a strong `STRUCTURAL_API_TOKEN`, then restart
and enter that token in Scientific Agents. This enables the authenticated
transport, not scientific computation. Retain all three gates as `false`:
`AGENT_COMPUTE_ENABLED`, `AGENT_ADMET_ENABLED`, `AGENT_LLM_ENABLED`.
Privately obtain the existing Scientific AI settings from the team; never copy
keys into source or chat. Token Factory remains optional for deterministic
preparation and blocked for inference without confirmed credentials.

## Continue and verify

```bash
cd ~/dockshift-integration/backend
uv run pytest tests -q
uv run ruff check app tests
cd ../frontend
npm test
npm run lint
npm run build
```

Read-only preparation and zero-budget protocol generation:

```bash
cd ~/dockshift-integration/backend
uv run python -m app.integration.prepare_science
# Use the actual preparation ID printed above and a NEW output filename:
uv run python -m app.integration.protocol_template ACTUAL_PREPARATION_ID --output final-protocol.json
uv run python -m app.integration.final_run final-protocol.json
```

The final command defaults to non-billable preflight. The generated protocol
contains exact prepared receptor/reference hashes and explicit missing
biologic/MD inputs, with zero submission and LLM budgets. It is not ready for
scientific execution until those inputs and reviews are completed. Runtime
resolves artifact bindings and rechecks the live Nebius schema before submission.
Store local protocols under the ignored artifact root, not in a commit.

Optional preparation utilities are `app.integration.system_builder` (dry-run
by default), `app.integration.system_bundle` and `app.integration.input_upload`
(no publishing by default). Do not use `--execute-local`, `--publish` or the
final-run `--execute` flag before separately approving the scientific work,
provider access and budget. Remote input-manifest conventions and unknown
output formats must be confirmed rather than guessed.

Local research results live in ignored `backend/.dockshift-agent-runs/` and
`backend/.dockshift-runs/`; scientific inputs belong in `.dockshift-inputs/`.
They are intentionally absent from Git and must be transferred separately via
an approved scientific artifact channel. The previously tracked `.env` is absent
from the branch's current tracked tree; old Git history is not rewritten.

The implementation follows the typed scientific state and bounded execution
patterns described by [BioNeMo Agent Toolkit](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit)
and [Aevom](https://github.com/NVIDIA-BioNeMo/agent-for-lifesciences), while retaining
Dockshift's runtime and services. No replacement framework/provider was installed.
