
## Meet the team

aleena iraqui - computational biologist, machine learning, biochemist, northeastern, broad

kiki chen - Architecture, design, workflow, pipeline, UI, UX - MS @ Harvard, MIT

Klaus - Mathematics, accelerate scientific discovery, AI/ML, Undergrad @ UMASS Amherst

hoang - computational biology, neuromodulation, mit, spaulding and harvard med school



## Table of contents

1. [Demo flow](#demo-flow)
2. [Architecture](#architecture)
3. [Multi-agent orchestration](#multi-agent-orchestration)
4. [Tech stack](#tech-stack)
5. [Quick start (local)](#quick-start-local)
6. [Environment variables](#environment-variables)
7. [API reference](#api-reference)
8. [Project structure](#project-structure)
9. [Resilience and fallbacks](#resilience-and-fallbacks)
10. [Deployment](#deployment)
11. [Development scripts](#development-scripts)
12. [Roadmap](#roadmap)
---

## Demo flow

Dockshift supports an hTERT discovery path: use the target-screening pipeline to rank the fixed
candidate set or discover literature-grounded molecules, select at most six candidates with the
published QSAR model, complete a separate literature checkpoint, obtain or run standalone AF3 for
an hTERT structure, align tcTERT to hTERT, compare fpocket pockets, create an immutable pocket-plan
artifact, and obtain scientist approval bound to its SHA-256 before dual-target AutoDock Vina
docking. Molecular dynamics remains a separate staged step because docking files do not contain
valid ligand parameters, solvent, ions, or a complete topology. The current runner does not resume
interrupted GROMACS runs.

## Architecture

`backend/app/main.py` serves FastAPI and the optionally mounted MCP server. Literature, QSAR,
target-screening pipeline, and structural services share models between REST and MCP. Structural adapters call configured external
scientific engines through shell-free asynchronous subprocesses with bounded streamed logs,
timeouts, and process-group cleanup. One process-wide admission controller limits all REST, HTTP
MCP, and stdio structural work, including geometry and planning. Each operation writes to a UUID
directory beneath `backend/.dockshift-runs` by default and returns
relative artifact references.

## Multi-agent orchestration

MCP exposes six literature/QSAR tools, three target-screening tools, plus preflight, TM-align,
official AlphaFold 3, preparation, fpocket, pocket comparison/box/planning, Vina, structural
workflow, and GROMACS tools. A selected pipeline entry maps its canonical `prediction.smiles` to
`CandidateLigand.smiles` for at most six ligands; preserve the QSAR prediction, profile, and
citations in `qsar_metadata`. A fixed shortlist does not complete the literature checkpoint.
The structural workflow requires exactly one to six candidates, a completed post-QSAR literature
checkpoint, exact tcTERT/hTERT structures, and scientist approval referencing the immutable pocket
proposal artifact and SHA-256. It verifies the proposal and current structure hashes, consumes the
saved pockets/transform/boxes without rerunning structural planning, and preserves candidate input
identity and completed stages when a later stage fails.

## Tech stack

Python 3.11+, FastAPI, Pydantic, MCP, RDKit, NumPy, SciPy, and XGBoost. Structural calculations use
external [TM-align](https://zhanggroup.org/TM-align/),
[AlphaFold 3](https://github.com/google-deepmind/alphafold3),
[fpocket](https://github.com/Discngine/fpocket),
[AutoDock Vina](https://vina.scripps.edu/), [Open Babel](https://openbabel.org/docs/), and
[GROMACS](https://www.gromacs.org/). These engines, AlphaFold 3 parameters, and databases are not
bundled.

## Quick start (local)

```bash
cd backend
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

OpenAPI is at `http://127.0.0.1:8000/docs`. HTTP MCP at
`http://127.0.0.1:8000/mcp` is absent by default; enable and authenticate it separately as
shown below. Workspace Kiro configuration remains on local stdio.

## Environment variables

Literature credentials, OpenAI-compatible target-proposal settings, and structural settings are
documented in `backend/.env.example`. Candidate proposal uses `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, `LLM_MODEL` (or `OPENAI_MODEL`), `LLM_TIMEOUT_SECONDS`, `LLM_MAX_DOCUMENTS`,
and `LLM_MAX_ABSTRACT_CHARS`. The
structural executable settings are `TMALIGN_EXECUTABLE`, `FPOCKET_EXECUTABLE`, `VINA_EXECUTABLE`,
`OBABEL_EXECUTABLE`, and `GROMACS_EXECUTABLE`. Official AlphaFold 3 runs additionally require
`ALPHAFOLD3_PYTHON_EXECUTABLE`, `ALPHAFOLD3_SCRIPT`, `ALPHAFOLD3_MODEL_DIR`, and
`ALPHAFOLD3_DATABASE_DIR`. Structural REST is disabled by default. Enabling it requires both
`STRUCTURAL_REST_ENABLED=true` and `STRUCTURAL_API_TOKEN`; execution requests use
`Authorization: Bearer <token>`. HTTP MCP is independently disabled by default. Enabling it
requires `MCP_HTTP_ENABLED=true` and a separate `MCP_HTTP_TOKEN`; every `/mcp` request must send
that token as Bearer authentication. An enabled transport without a token refuses to start. Local
MCP stdio remains available without either HTTP token. Runtime behavior uses separate
`STRUCTURAL_ARTIFACT_ROOT` and `STRUCTURAL_INPUT_ROOT` directories,
`STRUCTURAL_MAX_CONCURRENT_JOBS`, `STRUCTURAL_COMMAND_TIMEOUT_SECONDS`, and
`STRUCTURAL_LOG_MAX_BYTES`.

## API reference

Literature routes are under `/api/v1/literature`, hTERT QSAR under `/api/v1/qsar/htert`, target
screening under `/api/v1/pipeline`, and structural routes under `/api/v1/structural`. Every structural REST route, including the live
capabilities probe, is disabled by default and requires Bearer authentication when enabled.
Call `/api/v1/structural/capabilities` with that token before a structural run. See
`backend/README.md` for every
REST and MCP entry point, schemas, approval gates, the pocket similarity formula, and the
hTERT/tcTERT flow.

## Project structure

- `backend/app/agent/`: targets, LLM-backed candidate proposal, and QSAR shortlist pipeline
- `backend/app/literature/`: source adapters, ranking, and full text
- `backend/app/qsar/`: hTERT prediction, profiling, and model artifacts
- `backend/app/structural/`: external-engine adapters, artifacts, geometry, and workflow
- `backend/app/api/routes/`: REST routes
- `backend/app/mcp_server.py`: MCP service and tool registrations
- `frontend/`: dependency-free static interface

## Resilience and fallbacks

Literature sources and workflow ligands fail independently. Structural preflight reports missing
prerequisites without crashing the app. AlphaFold 3 has no silent ESMFold or other fallback.
Executable paths come only from Settings. Caller files come only from the dedicated structural
input root or existing artifact root, never arbitrary backend files. Commands stream bounded
stdout/stderr logs and terminate their process groups on timeout or cancellation.

## Deployment

Only local process execution is implemented. Container, scheduler, SSH, NVIDIA, Nebius, and other
remote execution are deployment responsibilities. Mount the artifact root on suitable persistent
storage and establish retention, access-control, resource-limit, and monitoring policies.

## Development scripts

Run `uv run ruff check .` and `uv run ruff format --check .` from `backend/`. The QSAR artifact
vendoring command is documented in `backend/README.md`.

## Roadmap

Remote execution backends and broader workflow scheduling may be added behind the existing
execution boundary. RFdiffusion is intentionally outside the current structural subsystem.
