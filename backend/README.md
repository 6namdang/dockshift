# Dockshift backend

FastAPI service + MCP server that lets agents search the literature:

| Source   | Backed by | Key needed | Full text |
|----------|-----------|------------|-----------|
| PubMed   | NCBI E-utilities | no (optional `NCBI_API_KEY`) | open-access PMC articles, via Europe PMC |
| bioRxiv  | Europe PMC preprint index | no | when Europe PMC holds it (`inEPMC=Y`) |
| ChemRxiv | Crossref (DOI prefix `10.26434`) | no | no (ChemRxiv PDFs sit behind Cloudflare) |
| Patents  | Lens.org Patent API (global) | **`LENS_API_TOKEN`** | claims + description |

Why not the "obvious" APIs: bioRxiv's API has no keyword search; ChemRxiv's API is behind
a Cloudflare bot challenge, and Europe PMC stopped indexing ChemRxiv in 2021; USPTO
PatentsView's search API went offline when it moved to the USPTO Open Data Portal in
March 2026.

## Setup

```bash
cd backend
uv sync                      # installs into backend/.venv
cp .env.example .env         # then fill in CONTACT_EMAIL, LENS_API_TOKEN, ...
```

## Run

```bash
uv run uvicorn app.main:app --reload            # REST + MCP on http://127.0.0.1:8000
```

- OpenAPI docs: <http://127.0.0.1:8000/docs>
- `GET  /health` reports which sources are configured
- `POST /api/v1/literature/search` takes `{"query": "...", "sources": [...], "max_results_per_source": 10, "year_from": 2020, "year_to": 2026, "full_text": "auto" | "never"}`
- `GET  /api/v1/literature/full-text/{id}` (e.g. `pubmed:31666701`)
- MCP (Streamable HTTP): `http://127.0.0.1:8000/mcp`

MCP server on its own:

```bash
uv run python -m app.mcp_server                 # stdio
uv run python -m app.mcp_server --http --port 8001
```

Add it to Claude Code / Claude Desktop (stdio):

```json
{
  "mcpServers": {
    "dockshift-literature": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/dockshift/backend", "python", "-m", "app.mcp_server"]
    }
  }
}
```

## MCP tools

- **`search_literature(query, sources?, max_results_per_source=10, year_from?, year_to?, full_text="auto")`**
  fans out to every selected source in parallel. It merges the hits, removes duplicates by
  DOI (keeping the newest ChemRxiv version), scores each hit, and returns them sorted by
  `confidence`. A source that fails is reported in `errors` and doesn't block the others.
- **`get_full_text(document_id)`**: full text for a single result id.

### Confidence and automatic full text

`confidence` (0 to 1) is a lexical score computed from the title and abstract
(`app/literature/scoring.py`):

```
0.55 × share of query terms present
0.20 × share of query terms in the title
0.15 × phrase proximity (query terms adjacent in the text)
0.10 × BM25 relative to the best hit in this result set
```

When `full_text="auto"`, full text is fetched only for hits with
`confidence >= FULLTEXT_CONFIDENCE_THRESHOLD` (default 0.75) whose full text can be
retrieved. At most `FULLTEXT_MAX_DOCS` (3) hits get it, and each text is truncated to
`FULLTEXT_MAX_CHARS` (20k). Each hit reports `full_text_status`: `fetched`, `unavailable`
or `error: …`.

## Layout

```
app/
  main.py              FastAPI app factory (+ mounts MCP at /mcp)
  config.py            Settings (env / .env)
  mcp_server.py        MCP server + tools
  api/routes/          REST routes (health, literature)
  literature/
    service.py         fan-out, merge, dedupe, score, auto full text
    scoring.py         lexical confidence
    models.py          Document / SearchRequest / SearchResponse
    http.py            shared httpx client + retries
    text.py            HTML/JATS → plain text
    sources/           pubmed.py, europepmc.py (bioRxiv), chemrxiv.py, patents.py
```

## Lint

```bash
uv run ruff check .
```
