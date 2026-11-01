"""Lazy, cached loading of the vendored hTERT QSAR artifacts.

Loading costs about a second (fingerprinting 616 training structures), so it happens on
first use rather than at import, and is cached for the process. Everything here is
synchronous and CPU-bound; callers run it in a worker thread.
"""

from __future__ import annotations

import csv
import json
import threading
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from app.qsar.chem import fingerprint, flat_smiles, standardise

DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class DatasetEntry:
    index: int
    smiles: str
    pic50: float
    n_measurements: int
    in_training_set: bool
    flat_smiles: str = ""


@dataclass
class Artifacts:
    model: Any
    descriptor_names: list[str]
    entries: list[DatasetEntry]
    card: dict[str, Any]
    train_fingerprints: list[Any] = field(default_factory=list)
    train_entries: list[DatasetEntry] = field(default_factory=list)

    @cached_property
    def by_smiles(self) -> dict[str, DatasetEntry]:
        return {entry.smiles: entry for entry in self.entries}

    @cached_property
    def by_flat_smiles(self) -> dict[str, list[DatasetEntry]]:
        """Entries keyed by structure with stereochemistry removed, best-supported first.

        The curated set holds stereoisomers as separate rows — BIBR1532 appears as both
        E and Z, with pIC50 5.30 (n=1) and 6.55 (n=15) — so a flat key can map to several
        entries and the caller has to say which it used.
        """
        groups: dict[str, list[DatasetEntry]] = {}
        for entry in self.entries:
            if entry.flat_smiles:
                groups.setdefault(entry.flat_smiles, []).append(entry)
        for group in groups.values():
            group.sort(key=lambda e: e.n_measurements, reverse=True)
        return groups

    @property
    def domain_threshold(self) -> float:
        return float(self.card["applicability_domain"]["threshold"])


_artifacts: Artifacts | None = None
_lock = threading.Lock()


def load_artifacts() -> Artifacts:
    """Return the process-wide artifacts, loading them on first call."""
    global _artifacts
    if _artifacts is not None:
        return _artifacts
    with _lock:
        if _artifacts is None:
            _artifacts = _build()
    return _artifacts


def _build() -> Artifacts:
    import xgboost

    # The native Booster API, rather than the XGBRegressor sklearn wrapper, so scikit-learn
    # is not a runtime dependency. The JSON is version-stable and executes no pickle.
    model = xgboost.Booster()
    model.load_model(str(DATA_DIR / "htert_xgboost_model.json"))

    descriptor_names = json.loads((DATA_DIR / "descriptor_names_kept.json").read_text())
    card = json.loads((DATA_DIR / "model_card.json").read_text())
    train_indices = set(json.loads((DATA_DIR / "train_indices.json").read_text()))

    entries: list[DatasetEntry] = []
    molecules: dict[int, Any] = {}
    with (DATA_DIR / "htert_curated_dataset.csv").open() as handle:
        for i, row in enumerate(csv.DictReader(handle)):
            mol = standardise(row["std_smiles"])
            if mol is not None:
                molecules[i] = mol
            entries.append(
                DatasetEntry(
                    index=i,
                    smiles=row["std_smiles"],
                    pic50=float(row["pIC50"]),
                    n_measurements=int(row["n_measurements"]),
                    in_training_set=i in train_indices,
                    flat_smiles=flat_smiles(mol) if mol is not None else "",
                )
            )

    expected = model.num_features()
    actual = 2048 + len(descriptor_names)
    if expected != actual:
        raise RuntimeError(
            f"Vendored artifacts are inconsistent: model expects {expected} features but "
            f"descriptor list implies {actual}. Re-run scripts/vendor_qsar_model.py."
        )

    artifacts = Artifacts(
        model=model, descriptor_names=descriptor_names, entries=entries, card=card
    )
    # Applicability domain and similarity search compare against training compounds only.
    # Both lists must stay index-aligned, so a structure that fails to parse drops from both.
    train_entries: list[DatasetEntry] = []
    train_fingerprints: list[Any] = []
    for entry in entries:
        if not entry.in_training_set:
            continue
        mol = molecules.get(entry.index)
        if mol is None:
            continue
        train_entries.append(entry)
        train_fingerprints.append(fingerprint(mol))
    artifacts.train_entries = train_entries
    artifacts.train_fingerprints = train_fingerprints
    return artifacts
