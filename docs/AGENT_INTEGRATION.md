# Run Dockshift with the integrated research workflow

The existing application is extended by `backend/app/integration/`, added agent
routes, the `AgentRunsView`, and `frontend/src/integration/researchApi.ts`.
The original QSAR, literature, structural engines and working views are reused.
See [verified execution and original-file audit](INTEGRATION_VERIFICATION.md).

## Clean checkout setup

Requires Python 3.11+ and uv, and Node 22.12+ for a fresh frontend build.

```sh
cd backend
uv sync --frozen --group dev
# Configure local settings using .env.example; preserve any existing .env.
uv run uvicorn app.main:app --reload
```

The tracked production frontend is served by the same backend at
`http://127.0.0.1:8000/ui/`. To rebuild it or develop React separately:

```sh
cd frontend
npm ci
npm run build -- --emptyOutDir false
# Or npm run dev; the existing Vite proxy forwards /api to localhost:8000.
```

No runtime import, Python environment, cache or artifact from
`Agentic_System_Test` is needed. Imported source digests and the original commit
are recorded in `backend/app/integration/scienceclaw/SOURCE.json`.

## Execution settings

Configure these in local backend settings or the process environment. Never put
keys in frontend code, public artifacts or committed configuration. The actual
`backend/.env` is untracked and ignored; use `.env.example` as the template.

- Existing `NEBIUS_API_KEY` / `SCIENTIFIC_MODELS_API_KEY` and MCP URL configure
  the scientific provider. Existing team settings retain their meanings.
- Existing `STRUCTURAL_REST_ENABLED=true` and a nonempty `STRUCTURAL_API_TOKEN`
  enable authenticated run execution, progress, reports and artifact access.
  Enter that token in the research view's password field; it stays in memory.
- `AGENT_ADMET_ENABLED=true` authorizes the narrow single-molecule ADMET path.
  The default is false. It does not authorize docking, generation, folding or MD.
- `AGENT_COMPUTE_ENABLED` remains false unless expensive jobs have been
  separately approved. Reviewed structural/design/topology inputs are also
  required; a missing prerequisite is a blocker, not a synthetic result.
- `AGENT_REMOTE_WAIT_SECONDS` bounds each poll window. Pending operations retain
  their IDs; **Resume recorded operations** polls the same IDs without submitting
  new inference. Successful operation data is never automatically acknowledged,
  purged or deleted. Resume works with submission gates disabled.
- Optional collective LLM reviews require `AGENT_LLM_ENABLED=true`, explicit
  `NEBIUS_LLM_API_KEY`, `NEBIUS_LLM_MODEL`, and the default
  `NEBIUS_LLM_BASE_URL=https://api.tokenfactory.nebius.com/v1`. The selected model
  is checked against the authenticated catalog before inference. This uses
  Nebius's [published inference interface](https://api.tokenfactory.nebius.com/docs).
  Other credentials are not silently forwarded to it. No local or alternative
  LLM is substituted. `use_local_llm` is retained only as a legacy request field;
  new requests select `use_nebius_llm`.

## Use the connected application

Select a candidate using the existing views, then open **Scientific Agents**
(shortcut 6). Only its name/SMILES is passed to the new view, never example
predictions or scores. Enter a name or SMILES, optional literature query, and
execution token, then click **Start research run**.

The backend independently verifies human hTERT with UniProt, resolves and
validates the molecule using the existing QSAR service, runs the existing
published model/profiles, and submits one candidate to Nebius ADMET-AI when
allowed. The UI polls individual workers, displays native ADMET values with
units/species and separate QSAR/measured fields, and offers authenticated,
hash-verified artifact downloads. Missing credentials, prerequisites, schemas,
results, byte integrity or scientific metadata produce explicit blockers or
failures. Raw endpoint values are not pooled or converted to binding potency.

The whole eight-worker runtime runs, but unsupported/unprepared branches block.
Candidate-screen completion is displayed separately from full-workflow status.
LLM review status and actual LLM invocation counts are separate from tool status.
All candidates remain research hypotheses requiring experiments. Artifact hashes,
input identity, methods, model/software versions and limitations are retained.

Runs and durable progress snapshots are stored beneath
`backend/.dockshift-agent-runs/` (configurable). A restarted process marks
unfinished work blocked and never automatically replays scientific jobs.
Admission is serialized per backend process. Use one API worker for this local
execution manager; it is not a distributed job scheduler. Advanced JSON inputs
and the previous synchronous `/agents/runs` endpoint remain available.

## Verification

```sh
cd backend
uv run pytest tests -q
uv run ruff check app tests
uv lock --check
cd ../frontend
npm test
npm run lint
npm run build -- --emptyOutDir false
```

Read [the verification record](INTEGRATION_VERIFICATION.md) for the live Nebius
operation, browser path, exact observed predictions, artifact digest, original
file modifications, regression coverage and remaining blocked science. Live
results are preserved locally, not bundled as demo data or used in default UI
state. Existing hashed build assets and historical scientific files are retained.
