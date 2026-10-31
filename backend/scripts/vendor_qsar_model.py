"""One-time vendoring of the hTERT QSAR artifacts into app/qsar/data/.

Source repo: https://github.com/AleenaI20/htert-qsar-xgboost (MIT)
Paper: Iraqui & Dang (2026), ChemRxiv 10.26434/chemrxiv.15005669/v2

Why this script exists:

* The upstream model ships as a joblib pickle. Unpickling executes arbitrary code and
  couples us to the exact xgboost/scikit-learn versions it was saved with, so we convert
  it once to xgboost's native JSON format, which is version-stable and needs no pickle.
* Upstream gitignores ``data/*.npy``, so the 80/20 split indices are absent. They are
  regenerable because scikit-learn's train_test_split permutation depends only on
  n_samples and random_state=42. We materialise them here so the runtime needs neither
  scikit-learn nor the .npy files.
* The applicability-domain threshold (5th percentile of the training set's leave-one-out
  max-Tanimoto distribution) is deterministic, so it is computed once and recorded.

Run it only to re-vendor (needs joblib, scikit-learn and the upstream clone):

    uv run --with joblib --with scikit-learn python scripts/vendor_qsar_model.py <clone>/data
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.simplefilter("ignore")

OUT_DIR = Path(__file__).resolve().parent.parent / "app" / "qsar" / "data"
TOP_FEATURES = 25


def main(src: Path) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    import joblib
    from rdkit import Chem, DataStructs
    from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator
    from sklearn.model_selection import train_test_split
    from xgboost import XGBRegressor

    # --- model: pickle -> native JSON ----------------------------------------
    estimator = joblib.load(src / "xgboost_final_model.pkl")
    model_path = OUT_DIR / "htert_xgboost_model.json"
    estimator.save_model(str(model_path))
    check = XGBRegressor()
    check.load_model(str(model_path))
    n_features = int(check.n_features_in_)
    print(f"model -> {model_path.name} ({n_features} features)")

    # --- descriptor names + dataset ------------------------------------------
    desc_kept = json.loads((src / "descriptor_names_kept.json").read_text())
    (OUT_DIR / "descriptor_names_kept.json").write_text(json.dumps(desc_kept))

    dataset_csv = (src / "htert_curated_dataset.csv").read_text()
    (OUT_DIR / "htert_curated_dataset.csv").write_text(dataset_csv)
    rows = list(csv.DictReader(dataset_csv.splitlines()))
    smiles = [r["std_smiles"] for r in rows]
    values = [float(r["pIC50"]) for r in rows]
    n = len(rows)
    assert n_features == 2048 + len(desc_kept), "feature count mismatch"

    # --- split indices (regenerated, then frozen) ----------------------------
    idx = np.arange(n)
    _, _, idx_train, idx_test = train_test_split(idx, idx, test_size=0.2, random_state=42)
    (OUT_DIR / "train_indices.json").write_text(json.dumps(sorted(int(i) for i in idx_train)))
    print(f"split -> train {len(idx_train)} / test {len(idx_test)}")

    # --- applicability-domain threshold --------------------------------------
    gen = GetMorganGenerator(radius=2, fpSize=2048)
    fps_all = [gen.GetFingerprint(Chem.MolFromSmiles(s)) for s in smiles]
    fps_train = [fps_all[i] for i in idx_train]
    loo_max = [
        max(DataStructs.BulkTanimotoSimilarity(fp, [o for j, o in enumerate(fps_train) if j != i]))
        for i, fp in enumerate(fps_train)
    ]
    threshold = round(float(np.percentile(loo_max, 5)), 3)
    print(f"applicability-domain threshold -> {threshold}")

    # --- provenance ----------------------------------------------------------
    benchmark = [
        {
            "algorithm": r["Algorithm"],
            "features": r["Features"],
            "cv_r2_mean": float(r["CV_R2_mean"]),
            "cv_r2_std": float(r["CV_R2_std"]),
        }
        for r in csv.DictReader((src / "benchmark_results.csv").read_text().splitlines())
    ]
    importances = [
        {"feature": r["Feature"], "importance": round(float(r["Importance"]), 5)}
        for r in csv.DictReader((src / "feature_importance.csv").read_text().splitlines())
    ][:TOP_FEATURES]

    card = {
        "target": "hTERT telomerase (ChEMBL target CHEMBL2916)",
        "endpoint": "pIC50 (-log10 of IC50 in molar)",
        "algorithm": "XGBoost regressor",
        "hyperparameters": json.loads((src / "best_params.json").read_text()),
        "features": {
            "total": n_features,
            "morgan_fingerprint_bits": 2048,
            "morgan_radius": 2,
            "rdkit_descriptors": len(desc_kept),
            "note": "Descriptors are selected by name, so the local RDKit version may hold "
            "a different total as long as these names exist.",
        },
        "training_data": {
            "source": "ChEMBL (target CHEMBL2916), IC50 records with standard_relation '='",
            "compounds": n,
            "pic50_min": round(min(values), 2),
            "pic50_max": round(max(values), 2),
            "pic50_mean": round(statistics.mean(values), 2),
            "pic50_sd": round(statistics.stdev(values), 2),
            "pic50_median": round(statistics.median(values), 2),
            "train_compounds": len(idx_train),
            "test_compounds": len(idx_test),
            "split": "80/20, random_state=42",
        },
        "performance": {
            "paper_nested_cv_r2": "0.508 +/- 0.070",
            "paper_heldout_r2": 0.533,
            "paper_heldout_rmse": 0.507,
            "paper_heldout_mae": 0.407,
            "paper_y_scrambling_p": 0.020,
            "reproduction_heldout_r2": 0.546,
            "reproduction_y_scrambling_p": 0.000,
            "interpretation": "R2 around 0.53 means roughly half the variance in potency is "
            "explained; predictions carry an error of about 0.5 log units and should be "
            "treated as rough triage, not measurement.",
        },
        "applicability_domain": {
            "metric": "Max Tanimoto similarity (Morgan r=2, 2048 bits) to a training compound",
            "threshold": threshold,
            "rule": "5th percentile of the training leave-one-out max-similarity distribution",
            "note": "Predictions for compounds below the threshold are extrapolation and "
            "unreliable.",
        },
        "benchmark": benchmark,
        "top_feature_importances": importances,
        "caveats": [
            "The paper's final model is XGBoost, but on this reproduction's feature set "
            "RandomForest scored slightly higher in cross-validation (0.533 vs 0.506); "
            "held-out performance is comparable.",
            "The curated dataset holds structures and pIC50 only; compound names and ChEMBL "
            "IDs are dropped during curation, so known compounds are found by structure.",
            "Predicted values are modelled estimates, never experimental measurements.",
        ],
        "citation": "Iraqui, A. & Dang, H. N. (2026). A Machine Learning QSAR Model for "
        "Predicting hTERT Telomerase Inhibitor Potency. ChemRxiv.",
        "doi": "10.26434/chemrxiv.15005669/v2",
        "source_repository": "https://github.com/AleenaI20/htert-qsar-xgboost",
        "license": "MIT",
    }
    (OUT_DIR / "model_card.json").write_text(json.dumps(card, indent=2) + "\n")
    print(f"provenance -> model_card.json ({len(benchmark)} benchmark rows)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]).resolve())
