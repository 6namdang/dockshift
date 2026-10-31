"""Schemas for the hTERT QSAR tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

MAX_COMPOUNDS = 50


class InputKind(StrEnum):
    SMILES = "smiles"
    NAME = "name"


class Domain(StrEnum):
    IN = "in"
    OUT = "out"


class CompoundRef(BaseModel):
    """What the caller asked for, and the structure it was resolved to."""

    query: str = Field(description="The name or SMILES string that was supplied.")
    smiles: str | None = Field(
        None, description="Standardised canonical SMILES (salts stripped, largest fragment)."
    )
    resolved_from: InputKind | None = Field(
        None, description="Whether the query was read as a SMILES string or looked up as a name."
    )
    pubchem_cid: int | None = Field(None, description="PubChem CID, when the name was looked up.")
    error: str | None = Field(
        None, description="Why this compound could not be processed; other fields are then unset."
    )


class ActivityPrediction(CompoundRef):
    predicted_pic50: float | None = Field(
        None, description="Predicted pIC50 (-log10 IC50 in molar). Higher means more potent."
    )
    predicted_ic50_nm: float | None = Field(None, description="The same prediction as IC50 in nM.")
    max_tanimoto: float | None = Field(
        None, description="Highest Tanimoto similarity to any training compound (0-1)."
    )
    domain: Domain | None = Field(
        None,
        description="'in' if max_tanimoto >= the domain threshold, else 'out' (extrapolation).",
    )
    measured_pic50: float | None = Field(
        None,
        description="Experimental pIC50 from ChEMBL when this exact structure is in the dataset.",
    )
    measured_count: int | None = Field(
        None, description="How many ChEMBL measurements the experimental value aggregates."
    )
    in_training_set: bool = Field(
        False,
        description="True if this structure was used to fit the model, making its prediction "
        "optimistic. Prefer measured_pic50 when present.",
    )


class PhysicochemicalProfile(CompoundRef):
    molecular_weight: float | None = None
    clogp: float | None = Field(None, description="Calculated octanol-water partition coefficient.")
    hbd: int | None = Field(None, description="Hydrogen-bond donors.")
    hba: int | None = Field(None, description="Hydrogen-bond acceptors.")
    tpsa: float | None = Field(
        None, description="Topological polar surface area (square angstrom)."
    )
    rotatable_bonds: int | None = None
    aromatic_rings: int | None = None
    qed: float | None = Field(None, description="Quantitative estimate of drug-likeness (0-1).")
    lipinski_violations: int | None = Field(
        None, description="Rule-of-five violations: MW>500, cLogP>5, HBD>5, HBA>10."
    )
    lipinski_pass: bool | None = Field(None, description="True when at most one rule is violated.")
    veber_pass: bool | None = Field(
        None, description="True when rotatable bonds <= 10 and TPSA <= 140."
    )


class DatasetMatch(BaseModel):
    smiles: str
    measured_pic50: float = Field(description="Experimental pIC50 aggregated from ChEMBL.")
    measured_count: int
    tanimoto: float = Field(description="Tanimoto similarity to the query structure.")
    in_training_set: bool = Field(description="Whether this compound was used to fit the model.")


class DatasetSearchResult(CompoundRef):
    exact_match: DatasetMatch | None = Field(
        None, description="Set when the query structure is itself in the curated dataset."
    )
    similar: list[DatasetMatch] = Field(
        default_factory=list, description="Nearest measured compounds, most similar first."
    )
    dataset_size: int = 0


class ActivityResponse(BaseModel):
    predictions: list[ActivityPrediction]
    domain_threshold: float = Field(
        description="Max-Tanimoto cutoff separating interpolation from extrapolation."
    )
    model_note: str


class ProfileResponse(BaseModel):
    profiles: list[PhysicochemicalProfile]


class ModelInfo(BaseModel):
    """Provenance and performance, so callers can caveat predictions properly."""

    info: dict[str, Any]
