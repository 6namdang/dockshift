
## Meet the team

aleena iraqui - computational biologist, machine learning, biochemist, northeastern, broad

kiki chen - Architecture, design, workflow, pipeline, UI, UX - MS @ Harvard, MIT

Klause - Mathematics, accelerate scientific discovery, AI/ML, Senior @ UMASS Amherst

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

The UI is a 4-step slider; each step is gated on the previous one and streams real data from the backend.

| Step | What the user does | What the system does |
|---|---|---|
| 01 · Question | Types or picks an example question | Validates length, unlocks step 2 |
| 02 · Validation | Reviews the literature QC card | Agent1 expands the query → OpenAlex / PubMed Central scan → Agent2 emits a `not_found` / `similar_work_exists` / `exact_match_found` signal and **flags the top 2 papers as prior work** |
| 03 · Hypotheses | Picks 1 of 3 hypotheses, fills the wet-lab planner | Agent3 (ESMFold) renders folding confidence for α7 / RIC-3; Agent2 ranks hypotheses against literature + folding |
| 04 · Experiment | Reads the masterplan and the **Agent4 Executable Report** | Agent2 writes the structured plan; Agent4 renders an extremely-clear, never-vague Markdown protocol (rendered with GFM tables, blockquoted notes, deliverable checkbox list) |

A second `Agent1 Evidence Stream` runs inside the validation step using **Server-Sent Events** so paper hits appear as they are found rather than at the end.

---

## Architecture

```
                  ┌──────────────────────────┐
                  │    Browser (Next.js)     │
                  │  4-step slider workspace │
                  └────────────┬─────────────┘
                               │  fetch / EventSource
                               ▼
                  ┌──────────────────────────┐
                  │   Next.js API routes     │  app/api/*
                  │   (server-side proxy)    │
                  └────────────┬─────────────┘
                               │  BACKEND_URL
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                       FastAPI (backend/main.py)                  │
│                                                                  │
│   /api/literature-qc   /api/hypotheses   /api/experiment-plan    │
│   /api/papers/stream (SSE)               /api/papers/{pmcid}     │
│                                                                  │
│   Agent1 ─► OpenAI o3-mini (query expansion)                     │
│           └► OpenAlex + PubMed Central (papers + full text)      │
│   Agent2 ─► OpenAI gpt-4o-mini (QC, hypotheses, masterplan)      │
│   Agent3 ─► UniProt + ESMFold (pLDDT, SVG structure thumbnail)   │
│   Agent4 ─► OpenAI gpt-4o-mini (executable wet-lab report)       │
│                                                                  │
│   SQLite cache (evidence.db) ── trafilatura/lxml paper extraction│
└──────────────────────────────────────────────────────────────────┘
```

Because the browser only ever talks to the **same-origin** Next API routes, **no CORS** configuration is required on the FastAPI service.

---

## Multi-agent orchestration

| Agent | Role | Engine | Falls back to |
|---|---|---|---|
| **Agent 1** | Rewrites the user's question into OpenAlex-friendly search strings, fetches ranked papers, hydrates full text from PubMed Central. | OpenAI `o3-mini` (or any reasoning model) + OpenAlex + PMC + `trafilatura` / `lxml` | Raw user query → OpenAlex search |
| **Agent 2** | Literature QC ("plagiarism check for science"), top-3 hypothesis ranking, structured masterplan generation. **Always flags the 2 closest prior-work papers** so the scientist can follow up. | OpenAI `gpt-4o-mini` | Deterministic QC + budget/timeline-aware planner that respects every wet-lab planner input |
| **Agent 3** | UniProt sequence fetch → ESMFold pLDDT → confidence label and base64-encoded SVG of the predicted backbone, attached to the matching hypothesis. | UniProt REST + ESMFold (`api.esmatlas.com` by default) | Skips the protein card when the sequence is too long or ESMFold rate-limits |
| **Agent 4** | Converts the structured plan into an extremely-clear, executable Markdown wet-lab report (transfection-style steps with volumes, durations, QC checkpoints, and a Fulcrum deliverable checklist). | OpenAI `gpt-4o-mini` | Deterministic Markdown report templated from the plan + planner context |

The endpoint always returns **HTTP 200** with a complete plan and report — Agent2/Agent4 failures are reported back via `agentMetadata.fallbackReasons` instead of bubbling up as a 5xx.

---

## Tech stack

**Frontend** — Next.js 16 (App Router) · React 19 · Tailwind CSS v4 · `react-markdown` + `remark-gfm` for the executable report · `lucide-react` icons.

**Backend** — Python 3.12 · FastAPI · Uvicorn · `requests` · `trafilatura` · `lxml` · `openai` SDK · SQLite (built-in).

**External services** — OpenAI (Agents 1/2/4), OpenAlex (open-access discovery), PubMed Central (full text), UniProt (sequences), ESMFold via ESM Atlas (structure + pLDDT). NCBI and Semantic Scholar API keys are optional rate-limit boosters.

---

## Quick start (local)

> Requires Python 3.12+ and Node.js 20+.

### 1. Clone and configure

```bash
git clone https://github.com/<your-org>/XtremeGene.git
cd XtremeGene

cp backend/.env.example backend/.env
# then edit backend/.env and add at minimum: OPENAI_API_KEY=...
```

### 2. Backend

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# dev server with hot reload on http://127.0.0.1:8000
fastapi dev
# (or) uvicorn main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/docs` for the auto-generated Swagger UI.

### 3. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
# open http://localhost:3000
```

The frontend defaults to `BACKEND_URL=http://127.0.0.1:8000`. Override by adding `BACKEND_URL=...` to `frontend/.env.local` if your backend lives elsewhere.

---

## Environment variables

Backend (`backend/.env`):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | recommended | — | Powers Agent1/2/4. Without it, deterministic fallbacks still produce a complete plan. |
| `OPENAI_AGENT1_MODEL` | optional | `o3-mini` | Reasoning model for query expansion. |
| `OPENAI_AGENT2_MODEL` | optional | `gpt-4o-mini` | Literature QC + hypothesis ranking + masterplan. |
| `OPENAI_AGENT4_MODEL` | optional | `gpt-4o-mini` | Executable wet-lab report. |
| `EVIDENCE_DB_PATH` | optional | `./evidence.db` | SQLite path. **Point at a persistent disk in production.** |
| `OPENALEX_USER_AGENT` | optional | repo URL | OpenAlex politeness header. |
| `MAX_PAPERS_DEFAULT` | optional | `10` | Paper-stream page size. |
| `OPENALEX_PER_PAGE_MULTIPLIER` | optional | `5` | Over-fetch factor before deduping. |
| `OPENALEX_TIMEOUT_SECONDS` / `PMC_TIMEOUT_SECONDS` | optional | `30` | Per-request HTTP timeouts. |
| `PAPER_FETCH_DELAY_SECONDS` | optional | `0.2` | Polite delay between PMC fetches. |
| `ESMFOLD_URL` | optional | ESM Atlas | Override for self-hosted ESMFold. |
| `ESMFOLD_MAX_LEN` / `ESMFOLD_OVERLAP` | optional | `400` / `20` | Sliding-window parameters for long sequences. |
| `NCBI_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY` | optional | — | Higher rate limits, otherwise unused. |
| `PORT` | optional | `8000` | Bind port (Render/Fly inject this automatically). |

Frontend (`frontend/.env.local`):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `BACKEND_URL` | recommended | `http://127.0.0.1:8000` | Where the Next API routes proxy to. |
| `NEXT_PUBLIC_BACKEND_URL` | optional | — | Falls back if `BACKEND_URL` is unset. |

---

## API reference

All POST endpoints accept and return JSON.

### `POST /api/literature-qc`

Request:
```json
{ "question": "Will C. elegans RIC-3 boost surface trafficking of human alpha7 nAChR vs human RIC-3 in HEK293T?" }
```

Response (`LiteratureQCResult`):
```json
{
  "novelty": "similar_work_exists",
  "summary": "Open-access scan returned 6 papers; the top 2 are flagged as the closest prior work.",
  "references": [
    { "title": "...", "url": "https://pmc.ncbi.nlm.nih.gov/...", "snippet": "...", "source": "PubMed Central" }
  ]
}
```

### `POST /api/hypotheses`

Body: `{ question, literature: LiteratureQCResult }`. Returns 3 ranked hypotheses plus the Agent3 protein folding cards (UniProt id, length, mean pLDDT, confidence label, base64 SVG thumbnail).

### `POST /api/experiment-plan`

Body: `{ question, literature, proteinModels?, plannerContext? }` where `plannerContext` carries the lab's budget cap, timeline weeks, available instruments / materials, required materials, preferred assays, and free-text notes. Always returns 200 with a complete plan and `executionReport` (Markdown).

### `GET /api/papers/stream?query=...&n=...`

Server-Sent Events stream. Each `data:` chunk is a JSON paper preview as soon as it is fetched and cached.

### `GET /api/papers/{pmcid}`

Full cached paper detail (text, figures, tables) for a previously streamed PMCID.

---

## Project structure

```
XtremeGene/
├── backend/
│   ├── main.py                       # FastAPI app, all 4 agents, SQLite, SSE
│   ├── protein-prediction-esmfold/   # Standalone ESMFold reference scripts
│   │   ├── agent2.py
│   │   ├── sequence_fetcher.py
│   │   ├── structure_predictor.py
│   │   └── visualizer.py
│   ├── requirements.txt
│   ├── .env.example
│   └── evidence.db                   # SQLite cache (gitignored at runtime)
└── frontend/
    ├── app/
    │   ├── api/
    │   │   ├── literature-qc/route.ts
    │   │   ├── hypotheses/route.ts
    │   │   ├── experiment-plan/route.ts
    │   │   └── papers/                # /stream + /[pmcid]
    │   ├── layout.tsx
    │   ├── page.tsx
    │   └── globals.css
    ├── components/
    │   ├── experiment-workspace.tsx   # 4-step slider, planner, plan UI
    │   ├── paper-evidence-panel.tsx   # SSE consumer
    │   ├── novelty-badge.tsx
    │   └── markdown.tsx               # GFM markdown renderer
    ├── lib/
    │   ├── api-client.ts
    │   ├── backend-proxy.ts
    │   └── types.ts
    ├── package.json
    └── next.config.ts
```

---

## Resilience and fallbacks

Every external dependency in this app is allowed to fail without taking the user flow with it.

- **No `OPENAI_API_KEY`?** Agent1 falls back to the raw user query, Agent2's literature QC returns a deterministic novelty signal + the 2 most-relevant fetched papers, the masterplan is generated from a parameterised template that respects budget cap, timeline, instruments-on-hand, materials-on-hand, materials-needed, preferred assays, and lab notes, and Agent4 renders the execution report from that same plan.
- **OpenAI rate-limited or returning bad JSON?** `response_format: json_object` plus a defensive parser, then the deterministic fallback. The endpoint surfaces what happened in `agentMetadata.fallbackReasons`.
- **PubMed Central full-text fetch fails?** Literature QC still surfaces OpenAlex metadata so the prior-work signal never disappears.
- **ESMFold over capacity / sequence too long?** The hypotheses step still ships; the protein card is hidden for that hypothesis.

That means the demo never blanks out — the worst case is a less-personalised plan, never a 5xx.

---

## Deployment

The frontend is stateless; the backend is a long-running Python process with SQLite + 30–60 s LLM calls + an SSE stream. **Do not deploy the FastAPI backend on Vercel** — Vercel's serverless functions cap at 10 s on Hobby / 60 s on Pro and have no persistent disk, so SQLite, ESMFold, and the literature-QC OpenAI calls will all crash with `FUNCTION_INVOCATION_FAILED`.

### Recommended: Vercel (frontend) + Render (backend, one-click)

A `render.yaml` Blueprint is already checked in at the repo root, plus `backend/Dockerfile` and `backend/.dockerignore`.

1. Push the repo to GitHub.
2. **Backend on Render**:
   - Go to <https://dashboard.render.com/blueprints> → **New Blueprint Instance** → connect your GitHub repo. Render reads `render.yaml`, creates the `xtremegene-backend` web service, attaches a 1 GB persistent disk at `/data`, and wires every non-secret env var.
   - In the service's **Environment** tab, fill in the secrets that were declared with `sync: false`:
     - `OPENAI_API_KEY` (required for live agents; the deterministic fallbacks still answer every endpoint without it).
     - `NCBI_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY` (optional rate-limit boosters).
   - Wait for the first build (~3–5 min). The health check at `/` should turn green.
   - Copy the public URL, e.g. `https://xtremegene-backend.onrender.com`.
3. **Frontend on Vercel**:
   - Import the same repo → Root Directory `frontend`.
   - Add the env var `BACKEND_URL=https://xtremegene-backend.onrender.com`.
   - Redeploy. The Next API routes (`/api/literature-qc`, `/api/hypotheses`, `/api/experiment-plan`, `/api/papers/stream`, `/api/papers/[pmcid]`) will now proxy to Render.

> **Plan note:** `render.yaml` uses `plan: starter` ($7/mo) because Render's free plan does not support persistent disks. For a free-tier demo, edit `render.yaml` to `plan: free` and delete the `disk:` block — `evidence.db` then lives in the container's ephemeral filesystem and is rebuilt on each deploy.

### Alternatives

- **Fly.io / Railway** — same `backend/Dockerfile`, attach a volume at `/data`, set the same env vars, point `BACKEND_URL` at the resulting URL.
- **One-host Docker Compose** — `backend/Dockerfile` + a Compose file that mounts a named volume at `/data`. Good for a single VM.

> **Vercel timeout note:** the SSE proxy through `app/api/papers/stream` keeps the connection open while the backend streams. Vercel Hobby caps server-route execution at 60 s, which is enough for today's flow; on Pro you can extend it via `export const maxDuration = 300` in that route file.

---

## Development scripts

Backend:

```bash
fastapi dev                                  # hot-reload dev server
uvicorn main:app --host 0.0.0.0 --port 8000  # production-style boot
python -m pytest                             # (no tests yet)
```

Frontend:

```bash
npm run dev      # next dev (port 3000)
npm run build    # production build
npm run start    # serve the production build
npm run lint     # eslint
```

---

## Roadmap

- [ ] Persist hypotheses + experiment plans per question in SQLite for share/reload.
- [ ] Push `materials` table into a real procurement integration (Fulcrum / Quartzy).
- [ ] Pluggable protein-prediction backend (Boltz / OmegaFold / self-hosted ESMFold).
- [ ] First-class auth for multi-user labs.
- [ ] Test suite with FastAPI's `TestClient` and Playwright E2E.

---

Built for Hack-Nation 2026 · α7 nAChR research.

