# Dockshift backend

FastAPI service + MCP server with three capabilities for drug-discovery agents:

1. **Literature search** across PubMed, bioRxiv, ChemRxiv, patents and PubChem
2. **hTERT QSAR** — telomerase-inhibition potency prediction and drug-likeness profiling
3. **Structural discovery** — external-engine integration for structure prediction, alignment,
   pockets, docking, and staged molecular dynamics

## Setup

```bash
cd backend
uv sync                      # installs into backend/.venv
cp .env.example .env         # then fill in CONTACT_EMAIL, LENS_API_TOKEN, ...
```

## Run

```bash
uv run uvicorn app.main:app --reload            # REST; HTTP MCP only when enabled
```

- **Frontend: <http://127.0.0.1:8000/ui/>**
- OpenAPI docs: <http://127.0.0.1:8000/docs>
- `GET /health` reports which sources are configured
- MCP (Streamable HTTP): absent by default; `MCP_HTTP_ENABLED=true` mounts authenticated `/mcp`

MCP server on its own. Stdio is local and needs no HTTP token. Standalone HTTP requires
`MCP_HTTP_ENABLED=true`, `MCP_HTTP_TOKEN`, and `Authorization: Bearer <token>` on every request:

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
| PubChem  | NCBI PUG-REST (compounds) | no (optional `NCBI_API_KEY`) | compound description |

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

---

# 3. Structural discovery

This subsystem is an executable integration layer around official scientific engines. It does
not reimplement their algorithms, and it does not bundle executables, AlphaFold 3 model
parameters, or sequence databases.

## External prerequisites

Install and license each tool according to its official project documentation:

- [TM-align](https://zhanggroup.org/TM-align/) for protein structural alignment
- [AlphaFold 3](https://github.com/google-deepmind/alphafold3) for optional local hTERT
  prediction. Its model parameters have separate access terms and its databases are external.
- [fpocket](https://github.com/Discngine/fpocket) for pocket detection
- [AutoDock Vina](https://vina.scripps.edu/) for docking
- [Open Babel](https://openbabel.org/docs/) for PDB/mmCIF conversion and PDBQT generation
- [GROMACS](https://www.gromacs.org/) for molecular dynamics

Configure paths in `backend/.env`:

| Setting | Default | Purpose |
|---|---|---|
| `STRUCTURAL_REST_ENABLED` | `false` | Opt in to structural REST job and mutation routes |
| `STRUCTURAL_API_TOKEN` | unset | Required Bearer secret whenever structural REST is enabled |
| `MCP_HTTP_ENABLED` | `false` | Independently opt in to mounted or standalone HTTP MCP |
| `MCP_HTTP_TOKEN` | unset | Separate Bearer secret required whenever HTTP MCP is enabled |
| `STRUCTURAL_MAX_CONCURRENT_JOBS` | `1` | One process-wide structural admission cap, bounded from 1 to 8 |
| `STRUCTURAL_ARTIFACT_ROOT` | `.dockshift-runs` | UUID-isolated runtime outputs beneath `backend/` when relative |
| `STRUCTURAL_INPUT_ROOT` | `.dockshift-inputs` | Dedicated caller-provided scientific inputs beneath `backend/` when relative |
| `STRUCTURAL_COMMAND_TIMEOUT_SECONDS` | `1800` | Per-command timeout (1–86400 seconds) |
| `STRUCTURAL_LOG_MAX_BYTES` | `10000000` | Hard bound for each streamed command log |
| `TMALIGN_EXECUTABLE` | `TMalign` | TM-align executable or absolute executable path |
| `FPOCKET_EXECUTABLE` | `fpocket` | fpocket executable |
| `VINA_EXECUTABLE` | `vina` | AutoDock Vina executable |
| `OBABEL_EXECUTABLE` | `obabel` | Open Babel executable |
| `GROMACS_EXECUTABLE` | `gmx` | GROMACS command wrapper |
| `ALPHAFOLD3_PYTHON_EXECUTABLE` | `python` | Python used for the official AF3 runner |
| `ALPHAFOLD3_SCRIPT` | unset | Path to official `run_alphafold.py` |
| `ALPHAFOLD3_MODEL_DIR` | unset | Licensed AF3 model-parameter directory |
| `ALPHAFOLD3_DATABASE_DIR` | unset | AF3 database directory |

Run `GET /api/v1/structural/capabilities` or MCP `structural_preflight` after setup. Missing
executables and AF3 assets are reported individually. They do not prevent the literature and
QSAR services from starting. AlphaFold 3 never falls back to another predictor. Dialect-v1
protein entries must provide `unpaired_msa` and `paired_msa` together or omit both. All inline AF3
text and canonical request metadata must remain within the approximately 3 MB request budget.
Omit large MSAs/templates and let the official AF3 data pipeline generate them; staged file-backed
AF3 inputs are not implemented. Standalone AF3 may include ligands and returns an explicit official
root-level `top_ranked_structure` as well as per-sample `structure_artifacts`.

Only the `local` execution backend is implemented. SSH, NVIDIA, Nebius, scheduler, container,
and cloud execution are deployment responsibilities; this API does not claim to implement
them.

## Safety and artifacts

Every operation creates a random UUID run directory beneath `STRUCTURAL_ARTIFACT_ROOT`.
Responses return artifact-root-relative references. Inputs may reference an existing artifact or a
file beneath the separate `STRUCTURAL_INPUT_ROOT`; arbitrary backend files, traversal, and symlink
escapes are rejected. Both roots are created at startup and ignored by Git.

Structural REST job and mutation routes are disabled by default. Set
`STRUCTURAL_REST_ENABLED=true` and configure a strong `STRUCTURAL_API_TOKEN` to enable them,
then send `Authorization: Bearer <token>`. HTTP MCP has a separate fail-closed boundary: set
`MCP_HTTP_ENABLED=true` and a different strong `MCP_HTTP_TOKEN`, then authenticate every `/mcp`
request with that Bearer token. The mounted endpoint is absent when disabled, and enabling it
without a token refuses startup. Standalone `--http` uses the same policy. MCP stdio remains a
local transport and needs no HTTP token. The live structural REST capabilities probe requires the
structural REST Bearer token because it starts configured executables; responses do not reveal
configured host paths.

Configured executables are never accepted from request bodies. Commands use argument arrays
with `asyncio` subprocesses, no shell, streamed size-bounded stdout/stderr logs, bounded timeouts,
and process-group cleanup on timeout, cancellation, and wrappers whose leader exits early.
`STRUCTURAL_MAX_CONCURRENT_JOBS` is one process-wide admission budget shared by every
`StructuralService` instance and includes pocket comparison, box computation, and proposal
creation. A failure returns a stable error code and relative log artifact references where
available.

## REST entry points

All routes are under `/api/v1/structural`. Every route below, including the live capabilities
probe, requires structural REST to be enabled and a valid Bearer token:

- `POST /tmalign` — metrics, both normalized TM-scores, and A-to-B rigid transform
- `POST /alphafold3` — official dialect-v1 JSON generation, configured local run, and explicit official root top model
- `POST /prepare/ligand` and `/prepare/receptor`
- `POST /fpocket`, `/pockets/compare`, `/pockets/box`, and `/pockets/plan`
- `POST /vina/dock`
- `POST /workflow` — bounded 1–6 candidate tcTERT/hTERT workflow
- `POST /gromacs/run` — staged `em -> nvt -> npt -> md`

The corresponding MCP tools are `structural_preflight`, `run_tmalign`, `run_alphafold3`,
`prepare_structural_ligand`, `prepare_structural_receptor`, `run_fpocket`,
`compare_structural_pockets`, `generate_structural_pocket_box`,
`create_structural_pocket_plan`, `run_vina_docking`, `run_structural_workflow`, and `run_gromacs`.
The original six literature/QSAR tools are unchanged. These tools need no token over stdio; HTTP
MCP requires its separate configured Bearer token.

## hTERT/tcTERT example flow

1. Rank one to six candidates with `predict_htert_activity`; record the returned QSAR fields in
   each workflow candidate's `qsar_metadata`.
2. Review literature and record citations/notes in `after_qsar_literature_checkpoint`.
3. Provide a tcTERT PDB/mmCIF structure and a reviewed hTERT structure. If hTERT prediction is
   needed, run standalone protein-only AF3 first, inspect its explicit `top_ranked_structure`, and
   use that exact artifact as `htert_structure`. The workflow does not accept inline AF3 and never
   substitutes a per-sample structure for the official root top model.
4. Use individual `run_tmalign`, `run_fpocket`, `compare_structural_pockets`, and
   `generate_structural_pocket_box` calls. Select exact returned pockets and boxes, then call
   `create_structural_pocket_plan` with both structure inputs, the TM-align result or exact
   transform, the complete selected Pocket objects, and exact boxes. Planning hashes both
   structures and writes a canonical proposal artifact whose SHA-256 binds the geometry,
   transform, boxes, comparison, and structure identities.
5. Present the proposal artifact, SHA-256, selected IDs, exact boxes, and comparison to the
   scientist. After explicit approval, submit `/workflow` with the same two structure references,
   completed literature checkpoint, and a `pocket_approval` containing `proposal_artifact`,
   `proposal_sha256`, `approved_by`, and a nonblank rationale. The workflow verifies the proposal
   digest, strict schema, canonical encoding, and current structure hashes. It consumes the saved
   pockets, transform, comparison, and boxes without rerunning AF3, TM-align, or fpocket. Partial
   candidate artifacts and immutable submitted SMILES/SDF identity remain in the result.
6. Inspect structures, protonation, metals, cofactors, pockets, boxes, and poses. Vina scores are
   triage signals rather than measured binding energies.
7. Separately parameterize the chosen protein-ligand complex with appropriate protein and ligand
   force fields, charges, solvent, ions, and topology. GROMACS `includes` entries contain `source`
   and a validated relative `destination`, such as `ligand/ligand.itp`, so topology layout is
   preserved. Submit the reviewed bundle and four MDP files to `/gromacs/run`.
8. After the GROMACS result, analyze energy and convergence outside this runner. Then call
   literature tools and record citations and notes in the agent ledger before proposing another
   chemical modification. GROMACS request/result models do not pretend a post-run checkpoint
   existed before execution.

The pocket composite is
`0.35*exp(-centroid_distance/5Å) + 0.45*symmetric_atom_overlap + 0.20*size_ratio`, where
`size_ratio` uses fpocket volume when both volumes exist and atom count otherwise. It is a
deterministic geometry heuristic, not evidence that pockets are biologically equivalent.

Ligand preparation uses RDKit to add hydrogens, generate a seeded 3D conformer, and request MMFF
or UFF optimization, then Open Babel creates PDBQT. The result records convergence status;
non-converged optimization retains geometry only with an explicit warning, and optimization
exceptions are typed failures. Receptor cleanup can remove waters, heterogens, and secondary
alternate locations before Open Babel creates rigid-receptor PDBQT. Users must inspect
protonation, tautomer state, atom typing, metals, cofactors, missing residues, and retained waters.

GROMACS consumes a fully prepared system bundle. The initial coordinate must have an allowlisted
`.gro`, `.pdb`, `.g96`, `.brk`, or `.ent` suffix, which is preserved while staging; unsupported or
missing suffixes fail before execution. Docking PDB/PDBQT files alone are not MD-ready, and this
subsystem intentionally does not invent ligand parameters or topologies. Successful Vina results
always include a non-empty pose artifact whose ATOM/HETATM-bearing model count and scores agree
with the parsed ranked modes. Missing, malformed, or inconsistent pose output is a typed parse
failure. The GROMACS runner calls
`gmx grompp` then `gmx mdrun` for each supplied MDP stage, stops on the first failure, and reports
stage artifacts/logs. It does not resume interrupted runs or derive energy/convergence metrics.
Those analyses are downstream scientist-reviewed work; completion does not establish equilibration,
convergence, or physical validity.

---

# 4. Frontend

A single static page (`frontend/index.html`) served by FastAPI at **`/ui/`** — no build
step, no npm, no dependencies. Enter compound names or SMILES and it shows:

- a **dot plot** of predicted pIC50 on a shared axis, with the measured value beside the
  prediction where ChEMBL has one (dots rather than bars: pIC50 is a log scale with no
  meaningful zero, and a truncated bar axis would mislead)
- per-compound **structure images** (PubChem), applicability-domain and drug-likeness
  **meters**, and status **badges** that always pair an icon with a label
- a **table view** of every value, so nothing is reachable only by hover
- light and dark themes, each with its own validated colour steps

Because it is served same-origin it needs no CORS exemption. Opening the file directly
also works: it falls back to `http://127.0.0.1:8000`.

## Layout

```
frontend/
  index.html           the whole UI: no build, no dependencies
app/
  main.py              FastAPI app factory (+ mounts MCP at /mcp)
  config.py            Settings (env / .env)
  mcp_server.py        MCP server + literature, QSAR, and structural tools
  api/routes/          REST routes (health, literature, qsar, structural)
  literature/
    service.py         fan-out, merge, dedupe, score, auto full text
    scoring.py         lexical confidence
    models.py          Document / SearchRequest / SearchResponse
    http.py            shared httpx client + retries
    text.py            HTML/JATS -> plain text
    sources/           pubmed.py, europepmc.py (bioRxiv), chemrxiv.py, patents.py, pubchem.py
  qsar/
    service.py         resolve -> predict / profile / dataset search
    artifacts.py       lazy cached model + training fingerprints
    chem.py            RDKit standardisation, featurisation, properties
    resolve.py         PubChem name -> SMILES
    models.py          prediction / profile / dataset schemas
    data/              vendored model + dataset + model card
  structural/
    service.py         REST/MCP facade and capability preflight
    execution.py       local shell-free subprocess backend with timeouts/logs
    artifacts.py       UUID workspaces and safe artifact references
    alphafold3.py      official AF3 JSON/local-runner adapter
    tmalign.py         TM-align execution and transform parsing
    preparation.py     RDKit/Open Babel ligand and receptor preparation
    pockets.py         fpocket parsing, comparison, docking-box geometry
    docking.py         AutoDock Vina execution and score parsing
    molecular_dynamics.py  staged GROMACS runner
    workflow.py        bounded tcTERT/hTERT candidate orchestration
scripts/
  vendor_qsar_model.py one-time artifact conversion from the upstream repo
```

## Lint

```bash
uv run ruff check .
```
