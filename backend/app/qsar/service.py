"""hTERT QSAR service: resolve compounds, predict potency, profile, search the dataset.

The model is the one published with Iraqui & Dang (2026) and reused as-is (no retraining).
Predictions are modelled estimates with roughly half-a-log-unit error, so every result
carries its applicability-domain status and, where a real measurement exists, that value.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from rdkit import Chem

from app.config import Settings, get_settings
from app.literature.http import SourceUnavailableError
from app.qsar import chem
from app.qsar.artifacts import Artifacts, DatasetEntry, load_artifacts
from app.qsar.models import (
    MAX_COMPOUNDS,
    ActivityPrediction,
    ActivityResponse,
    CompoundRef,
    DatasetMatch,
    DatasetSearchResult,
    Domain,
    InputKind,
    PhysicochemicalProfile,
    ProfileResponse,
)
from app.qsar.resolve import resolve_name

logger = logging.getLogger(__name__)

MODEL_NOTE = (
    "Predicted values come from an XGBoost QSAR model (held-out R^2 ~0.53, error ~0.5 log "
    "units): useful for ranking and triage, not a substitute for measurement. Treat "
    "domain='out' results as unreliable extrapolation, and prefer measured_pic50 when present."
)


class QsarService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings | None = None) -> None:
        self.client = client
        self.settings = settings or get_settings()

    # ------------------------------------------------------------- resolution
    async def _resolve(self, query: str) -> tuple[CompoundRef, Chem.Mol | None]:
        """Turn a name or SMILES into a standardised molecule."""
        text = (query or "").strip()
        if not text:
            return CompoundRef(query=query, error="Empty compound query."), None

        mol = chem.standardise(text)
        if mol is not None:
            return (
                CompoundRef(
                    query=text,
                    smiles=chem.canonical_smiles(mol),
                    resolved_from=InputKind.SMILES,
                ),
                mol,
            )

        # Not a parsable structure, so treat it as a name.
        try:
            found = await resolve_name(self.client, self.settings, text)
        except SourceUnavailableError as exc:
            return CompoundRef(query=text, error=f"Name lookup failed: {exc}"), None
        if found is None:
            return (
                CompoundRef(
                    query=text,
                    error="Not a valid SMILES string, and PubChem has no compound with this name.",
                ),
                None,
            )
        smiles, cid = found
        mol = chem.standardise(smiles)
        if mol is None:
            return (
                CompoundRef(
                    query=text,
                    resolved_from=InputKind.NAME,
                    pubchem_cid=cid,
                    error=f"PubChem structure for this name could not be parsed: {smiles}",
                ),
                None,
            )
        return (
            CompoundRef(
                query=text,
                smiles=chem.canonical_smiles(mol),
                resolved_from=InputKind.NAME,
                pubchem_cid=cid,
            ),
            mol,
        )

    async def _resolve_many(self, queries: list[str]) -> list[tuple[CompoundRef, Chem.Mol | None]]:
        return list(await asyncio.gather(*(self._resolve(q) for q in queries)))

    @staticmethod
    def _check_count(queries: list[str]) -> list[str]:
        if not queries:
            raise ValueError("Provide at least one compound.")
        if len(queries) > MAX_COMPOUNDS:
            raise ValueError(f"At most {MAX_COMPOUNDS} compounds per call, got {len(queries)}.")
        return queries

    # ------------------------------------------------------------- prediction
    async def predict_activity(self, compounds: list[str]) -> ActivityResponse:
        self._check_count(compounds)
        resolved = await self._resolve_many(compounds)
        artifacts = await asyncio.to_thread(load_artifacts)
        predictions = await asyncio.to_thread(self._predict_sync, artifacts, resolved)
        return ActivityResponse(
            predictions=predictions,
            domain_threshold=artifacts.domain_threshold,
            model_note=MODEL_NOTE,
        )

    def _predict_sync(
        self, artifacts: Artifacts, resolved: list[tuple[CompoundRef, Chem.Mol | None]]
    ) -> list[ActivityPrediction]:
        results: list[ActivityPrediction] = []
        for ref, mol in resolved:
            if mol is None:
                results.append(ActivityPrediction(**ref.model_dump()))
                continue
            try:
                results.append(self._predict_one(artifacts, ref, mol))
            except Exception as exc:
                logger.exception("QSAR prediction failed for %s", ref.query)
                data = ref.model_dump()
                data["error"] = f"Prediction failed: {type(exc).__name__}: {exc}"
                results.append(ActivityPrediction(**data))
        return results

    def _predict_one(
        self, artifacts: Artifacts, ref: CompoundRef, mol: Chem.Mol
    ) -> ActivityPrediction:
        features = chem.featurise(mol, artifacts.descriptor_names)
        # inplace_predict takes the numpy row directly and treats NaN as missing.
        pic50 = float(artifacts.model.inplace_predict(features)[0])

        similarities = chem.bulk_tanimoto(mol, artifacts.train_fingerprints)
        max_tanimoto = max(similarities) if similarities else 0.0
        threshold = artifacts.domain_threshold

        known: DatasetEntry | None = artifacts.by_smiles.get(ref.smiles or "")
        return ActivityPrediction(
            **ref.model_dump(),
            predicted_pic50=round(pic50, 2),
            predicted_ic50_nm=round(10 ** (-pic50) * 1e9, 1),
            max_tanimoto=round(max_tanimoto, 2),
            domain=Domain.IN if max_tanimoto >= threshold else Domain.OUT,
            measured_pic50=round(known.pic50, 2) if known else None,
            measured_count=known.n_measurements if known else None,
            in_training_set=bool(known and known.in_training_set),
        )

    # --------------------------------------------------------------- profiling
    async def profile(self, compounds: list[str]) -> ProfileResponse:
        self._check_count(compounds)
        resolved = await self._resolve_many(compounds)
        profiles = await asyncio.to_thread(self._profile_sync, resolved)
        return ProfileResponse(profiles=profiles)

    @staticmethod
    def _profile_sync(
        resolved: list[tuple[CompoundRef, Chem.Mol | None]],
    ) -> list[PhysicochemicalProfile]:
        profiles: list[PhysicochemicalProfile] = []
        for ref, mol in resolved:
            if mol is None:
                profiles.append(PhysicochemicalProfile(**ref.model_dump()))
                continue
            try:
                profiles.append(PhysicochemicalProfile(**ref.model_dump(), **chem.properties(mol)))
            except Exception as exc:
                logger.exception("Profiling failed for %s", ref.query)
                data = ref.model_dump()
                data["error"] = f"Profiling failed: {type(exc).__name__}: {exc}"
                profiles.append(PhysicochemicalProfile(**data))
        return profiles

    # ---------------------------------------------------------- dataset search
    async def search_dataset(self, compound: str, limit: int = 5) -> DatasetSearchResult:
        ref, mol = await self._resolve(compound)
        artifacts = await asyncio.to_thread(load_artifacts)
        if mol is None:
            return DatasetSearchResult(**ref.model_dump(), dataset_size=len(artifacts.entries))
        return await asyncio.to_thread(self._search_sync, artifacts, ref, mol, limit)

    @staticmethod
    def _search_sync(
        artifacts: Artifacts, ref: CompoundRef, mol: Chem.Mol, limit: int
    ) -> DatasetSearchResult:
        exact_entry = artifacts.by_smiles.get(ref.smiles or "")
        exact = (
            DatasetMatch(
                smiles=exact_entry.smiles,
                measured_pic50=round(exact_entry.pic50, 2),
                measured_count=exact_entry.n_measurements,
                tanimoto=1.0,
                in_training_set=exact_entry.in_training_set,
            )
            if exact_entry
            else None
        )

        similarities = chem.bulk_tanimoto(mol, artifacts.train_fingerprints)
        ranked = sorted(
            zip(artifacts.train_entries, similarities, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        similar = [
            DatasetMatch(
                smiles=entry.smiles,
                measured_pic50=round(entry.pic50, 2),
                measured_count=entry.n_measurements,
                tanimoto=round(score, 3),
                in_training_set=entry.in_training_set,
            )
            for entry, score in ranked[: max(1, min(limit, 25))]
        ]
        return DatasetSearchResult(
            **ref.model_dump(),
            exact_match=exact,
            similar=similar,
            dataset_size=len(artifacts.entries),
        )

    # ------------------------------------------------------------- provenance
    async def model_info(self) -> dict:
        artifacts = await asyncio.to_thread(load_artifacts)
        return artifacts.card
