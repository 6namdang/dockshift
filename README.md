# Dockshift

Dockshift shortlists candidate small-molecule inhibitors for a protein target. It
combines a literature search across PubMed, bioRxiv, ChemRxiv and PubChem with a
published QSAR model that estimates inhibitory potency, and ranks the candidates by
predicted potency alongside their applicability-domain status and drug-likeness.

The current target is **hTERT telomerase** (ChEMBL `CHEMBL2916`).

---

## Contents

- [Quick start](#quick-start)
- [Workflows](#workflows)
- [The QSAR model](#the-qsar-model)
- [Interfaces](#interfaces)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Development](#development)
- [Limitations](#limitations)
- [Team](#team)
- [Citation and licence](#citation-and-licence)

---

## Quick start

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
cp .env.example .env     # optional; only the Literature workflow needs a key
uv run uvicorn app.main:app --reload
```

| | |
|---|---|
| Web interface | <http://127.0.0.1:8000/ui/> |
| API reference | <http://127.0.0.1:8000/docs> |
| Health check | <http://127.0.0.1:8000/health> |
| MCP endpoint | `http://127.0.0.1:8000/mcp` |

One process serves all of them: the frontend is a dependency-free static page served by
FastAPI, so there is no separate build step.

---

## Workflows

Each workflow produces the same output — candidate molecules ranked by predicted
potency, with applicability domain, drug-likeness and chemotype clustering — and they
differ only in where the candidates come from.

### 1. Screen

Scores the target's defined candidate set. hTERT ships with the six prospective
compounds assessed in the source paper: BIBR1532, quercetin, EGCG, allicin, zidovudine
and raltitrexed. No network calls beyond structure resolution, and no API key.

### 2. Literature

Searches the literature for inhibitors of the target, has a language model propose
candidate compounds grounded in the retrieved abstracts, and scores the survivors.

Proposals are filtered before scoring. A compound must resolve to a real structure in
PubChem, and must pass a small-molecule check — molecular weight ≤ 900, ≤ 20 rotatable
bonds, ≤ 60 heavy atoms. The limits are the 95th percentile of the model's own training
set. Rejections are reported with their reason rather than dropped silently.

This check is not cosmetic. The model's ChEMBL training data contains a tail of
oligonucleotides, up to 4,910 Da, so fingerprint similarity alone will rate a 13-mer
oligonucleotide as inside the applicability domain. Size has to be checked explicitly.

Requires `OPENAI_API_KEY`, or any OpenAI-compatible endpoint.

### 3. Library

Ranks 10,000 real ChEMBL compounds by structural similarity to a molecule already known
to act on the target, clusters the top of that ranking so the picks are distinct
chemotypes rather than near-duplicates, and scores the picks.

Every hit is an existing library compound, so unlike the literature route nothing can be
invented. Ranking is O(n) and effectively free; clustering is O(n²) and runs only over
the shortlist; the QSAR model runs over the handful of picks, never the full library.
A screen takes about 2.3 seconds once the library is cached, and needs no API key.

The library is NVIDIA's nvMolKit benchmark set, fetched once (789 KB) and cached.

---

## The QSAR model

The model is reused as published; nothing is retrained.

| | |
|---|---|
| Algorithm | XGBoost regressor |
| Endpoint | pIC50 (−log₁₀ IC50 in molar) |
| Features | 2,048-bit Morgan fingerprint (radius 2) + 195 RDKit 2D descriptors = 2,243 |
| Training data | 616 ChEMBL compounds for `CHEMBL2916`, pIC50 4.03–8.34 |
| Held-out performance | R² 0.533, RMSE 0.507, MAE 0.407 |
| Applicability domain | maximum Tanimoto to a training compound ≥ 0.272 |

The applicability-domain threshold is the 5th percentile of the training set's
leave-one-out maximum-similarity distribution.

The upstream model ships as a joblib pickle. It is converted once to XGBoost's native
JSON format (`backend/scripts/vendor_qsar_model.py`), so the service executes no pickle
and is not pinned to the library versions the model was saved with.

---

## Interfaces

### REST

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/pipeline/targets` | Available targets and whether each has a model |
| `POST` | `/api/v1/pipeline/{target}/shortlist` | Score the target's candidate set |
| `POST` | `/api/v1/pipeline/{target}/library-screen` | Screen the compound library |
| `POST` | `/api/v1/pipeline/{target}/literature-shortlist` | Candidates from the literature |
| `POST` | `/api/v1/literature/search` | Search across all literature sources |
| `GET` | `/api/v1/literature/full-text/{id}` | Open-access full text |
| `POST` | `/api/v1/qsar/htert/predict` | Potency for arbitrary compounds |
| `POST` | `/api/v1/qsar/htert/profile` | Physicochemical and drug-likeness properties |
| `GET` | `/api/v1/qsar/htert/dataset` | Nearest measured compounds |
| `GET` | `/api/v1/qsar/htert/structure` | Structure as SVG, rendered locally |
| `GET` | `/api/v1/qsar/htert/model` | Model provenance and performance |

### MCP

The same capabilities are exposed as ten MCP tools: `list_targets`,
`shortlist_inhibitors`, `screen_compound_library`, `find_candidates_in_literature`,
`search_literature`, `get_full_text`, `predict_htert_activity`, `profile_compound`,
`search_htert_dataset` and `get_htert_model_info`.

Over stdio:

```bash
uv run python -m app.mcp_server
```

In a client configuration:

```json
{
  "mcpServers": {
    "dockshift": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/dockshift/backend",
               "python", "-m", "app.mcp_server"]
    }
  }
}
```

---

## Configuration

Settings live in `backend/.env`; see `backend/.env.example`. Everything is optional
except where a workflow needs it.

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required by the Literature workflow only |
| `OPENAI_MODEL` / `LLM_MODEL` | Model name; defaults to `gpt-4o-mini` |
| `OPENAI_BASE_URL` | For any OpenAI-compatible endpoint |
| `CONTACT_EMAIL` | Sent to NCBI and Crossref; improves rate limits |
| `NCBI_API_KEY` | Raises the PubMed limit from 3 to 10 requests/second |
| `FULLTEXT_CONFIDENCE_THRESHOLD` | When full text is fetched automatically |

The Screen and Library workflows need no credentials.

---

## Project layout

```
backend/
  app/
    main.py              FastAPI application; serves the API, the UI and MCP
    mcp_server.py        MCP server and tool definitions
    config.py            Settings
    agent/               Target definitions and the three workflows
    literature/          Source adapters, merging, lexical ranking
    qsar/                Model, featurisation, clustering, library screen
      data/              Vendored model, dataset and model card
    api/routes/          REST routes
  scripts/
    vendor_qsar_model.py One-time conversion of the upstream model artifacts
frontend/
  index.html             The entire interface; no build step
```

---

## Development

```bash
cd backend
uv run ruff check .      # lint
uv run ruff format .     # format
```

---

## Limitations

- Predicted potencies are model estimates with roughly half a log unit of error. They
  are suitable for ranking and triage, not as a substitute for measurement.
- A result marked outside the applicability domain is extrapolation and should not be
  relied on.
- Compounds that were part of the training set are flagged; their predictions are
  optimistic, and the measured value is shown alongside where ChEMBL has one.
- Candidates proposed from the literature reflect what the retrieved abstracts say, not
  evidence of activity.
- Only hTERT has a trained model. Another target requires its own.
- Nothing here has been experimentally validated.

---

## Team

**Aleena Iraqui** — computational biology, machine learning, biochemistry. Northeastern, Broad Institute.

**Kiki Chen** — architecture, design, workflow, pipeline, UI/UX. MS, Harvard and MIT.

**Klaus** — mathematics, accelerating scientific discovery, AI/ML. Undergraduate, UMass Amherst.

**Hoang** — computational biology, neuromodulation. MIT, Spaulding and Harvard Medical School.

---

## Citation and licence

The QSAR model and its curated dataset come from:

> Iraqui, A. & Dang, H. N. (2026). *A Machine Learning QSAR Model for Predicting hTERT
> Telomerase Inhibitor Potency: ChEMBL Dataset Curation, Algorithm Benchmarking, and
> Prospective Application to Natural and Synthetic Anticancer Compounds.* ChemRxiv.
> [10.26434/chemrxiv.15005669/v2](https://doi.org/10.26434/chemrxiv.15005669/v2)

Source repository: [AleenaI20/htert-qsar-xgboost](https://github.com/AleenaI20/htert-qsar-xgboost) (MIT).

Bioactivity data from [ChEMBL](https://www.ebi.ac.uk/chembl/); compound structures from
[PubChem](https://pubchem.ncbi.nlm.nih.gov/). The similarity-screening and clustering
approach follows NVIDIA's `science-kits-for-agents` `screen-molecules` kit, and the
compound library is its nvMolKit benchmark set.
