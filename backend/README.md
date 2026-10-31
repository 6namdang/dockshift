# Dockshift backend

FastAPI service + MCP server with two capabilities for drug-discovery agents:

1. **Literature search** across PubMed, bioRxiv, ChemRxiv and patents
2. **hTERT QSAR** — telomerase-inhibition potency prediction and drug-likeness profiling

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
- `GET /health` reports which sources are configured
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
    "dockshift": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/dockshift/backend", "python", "-m", "app.mcp_server"]
    }
  }
}
```

---

# 1. Literature search

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

**MCP tools**

- **`search_literature(query, sources?, max_results_per_source=10, year_from?, year_to?, full_text="auto")`**
  fans out to every selected source in parallel, merges hits, removes duplicates by DOI
  (keeping the newest ChemRxiv version), scores each hit and sorts by `confidence`. A
  source that fails is reported in `errors` and doesn't block the others.
- **`get_full_text(document_id)`** — full text for a single result id.

**REST**

- `POST /api/v1/literature/search`
- `GET  /api/v1/literature/full-text/{id}` (e.g. `pubmed:31666701`)

### Confidence and automatic full text

`confidence` (0 to 1) is a lexical score from title and abstract (`app/literature/scoring.py`):

```
0.55 × share of query terms present
0.20 × share of query terms in the title
0.15 × phrase proximity (query terms adjacent in the text)
0.10 × BM25 relative to the best hit in this result set
```

With `full_text="auto"`, full text is fetched only for hits at or above
`FULLTEXT_CONFIDENCE_THRESHOLD` (0.75) whose text is retrievable, capped at
`FULLTEXT_MAX_DOCS` (3) and truncated to `FULLTEXT_MAX_CHARS` (20k). Each hit reports
`full_text_status`: `fetched`, `unavailable` or `error: …`.

---

# 2. hTERT QSAR

Predicts hTERT telomerase-inhibition potency (pIC50) from molecular structure. This is a
**ligand-based** model: it uses the compound's own structure, with no protein structure
and no docking.

The trained model is **reused as published** — nothing is retrained. Source:
[AleenaI20/htert-qsar-xgboost](https://github.com/AleenaI20/htert-qsar-xgboost) (MIT),
from Iraqui & Dang (2026), ChemRxiv [10.26434/chemrxiv.15005669/v2](https://doi.org/10.26434/chemrxiv.15005669/v2).

| | |
|---|---|
| Algorithm | XGBoost regressor (the paper's final model) |
| Features | 2048-bit Morgan fingerprint (radius 2) + 195 RDKit 2D descriptors = 2243 |
| Training data | 616 ChEMBL compounds for target CHEMBL2916, pIC50 4.03–8.34 |
| Held-out performance | R² ≈ 0.53, RMSE ≈ 0.51 (~0.5 log units of error) |
| Applicability domain | max Tanimoto to a training compound ≥ **0.272** |

**MCP tools**

- **`predict_htert_activity(compounds)`** — pIC50 and IC50 (nM) per compound, plus
  `max_tanimoto`, `domain` (`in`/`out`), and `measured_pic50` / `in_training_set` when the
  compound has real ChEMBL data.
- **`profile_compound(compounds)`** — MW, cLogP, HBD/HBA, TPSA, rotatable bonds, aromatic
  rings, QED, Lipinski violations, Veber pass/fail. Pure RDKit, no model.
- **`search_htert_dataset(compound, limit=5)`** — exact structure match plus nearest
  measured compounds by Tanimoto. Curation drops compound names, so matches are returned
  as SMILES.
- **`get_htert_model_info()`** — training data, performance, applicability domain,
  algorithm benchmark, feature importances, caveats, citation and DOI.

Compounds are given as **names or SMILES**; names resolve through PubChem (no key). Up to
50 per call.

**REST**

- `POST /api/v1/qsar/htert/predict` — body: `["quercetin", "EGCG"]`
- `POST /api/v1/qsar/htert/profile`
- `GET  /api/v1/qsar/htert/dataset?compound=quercetin&limit=5`
- `GET  /api/v1/qsar/htert/model`

### Reading the output honestly

- Predictions are **estimates, not measurements**. At R² ≈ 0.53 they are useful for
  ranking and triage only.
- `domain: "out"` means the compound is unlike anything in the training set, so the
  prediction is extrapolation and unreliable.
- `in_training_set: true` means the model was fitted on that compound, so its prediction
  is optimistic — prefer `measured_pic50`.

### Vendored artifacts

`app/qsar/data/` holds about 528 KB: the model as **xgboost native JSON** (converted from
the upstream joblib pickle, so no pickle is executed and no library versions are pinned),
the 616-compound dataset, the 195 descriptor names, the frozen 80/20 train indices, and a
model card. Regenerate with:

```bash
uv run --with joblib --with scikit-learn python scripts/vendor_qsar_model.py <clone>/data
```

Two notes on reproducing the upstream numbers:

- The shipped model reproduces the upstream repo's committed
  `prospective_predictions.csv` exactly, and the applicability-domain threshold
  reproduces at 0.272.
- Upstream `05_prospective_predictions.py` hardcodes **incorrect SMILES** for allicin
  (missing one sulfur), BIBR1532 and raltitrexed (different scaffolds) — its own
  `06_physicochemical_profiling.py` uses the correct ones. Because this backend resolves
  structures through PubChem, its Tanimoto and domain results match the **paper's Table 1**
  for all six compounds, where that upstream script does not.

## Layout

```
app/
  main.py              FastAPI app factory (+ mounts MCP at /mcp)
  config.py            Settings (env / .env)
  mcp_server.py        MCP server + all six tools
  api/routes/          REST routes (health, literature, qsar)
  literature/
    service.py         fan-out, merge, dedupe, score, auto full text
    scoring.py         lexical confidence
    models.py          Document / SearchRequest / SearchResponse
    http.py            shared httpx client + retries
    text.py            HTML/JATS -> plain text
    sources/           pubmed.py, europepmc.py (bioRxiv), chemrxiv.py, patents.py
  qsar/
    service.py         resolve -> predict / profile / dataset search
    artifacts.py       lazy cached model + training fingerprints
    chem.py            RDKit standardisation, featurisation, properties
    resolve.py         PubChem name -> SMILES
    models.py          prediction / profile / dataset schemas
    data/              vendored model + dataset + model card
scripts/
  vendor_qsar_model.py one-time artifact conversion from the upstream repo
```

## Lint

```bash
uv run ruff check .
```
