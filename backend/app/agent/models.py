"""Schemas for the target -> candidate molecules -> QSAR results pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.qsar.models import ActivityPrediction, PhysicochemicalProfile

DEFAULT_SHORTLIST = 6
MAX_SHORTLIST = 12
MAX_PROPOSALS = 16


class CandidateSpec(BaseModel):
    """A molecule in a target's candidate set."""

    name: str
    note: str = Field(description="What the compound is, in one line.")


class Target(BaseModel):
    id: str = Field(description="Short target id, e.g. 'htert'.")
    name: str
    description: str
    chembl_id: str | None = None
    qsar_available: bool = Field(
        description="Whether a trained QSAR model exists to score candidates for this target."
    )
    search_query: str = Field(
        "", description="Default literature query used when looking for inhibitors."
    )
    candidates: list[CandidateSpec] = Field(
        default_factory=list, description="The candidate molecules screened against this target."
    )


class DroppedCandidate(BaseModel):
    name: str
    reason: str


class ShortlistEntry(BaseModel):
    rank: int
    name: str
    note: str
    prediction: ActivityPrediction
    profile: PhysicochemicalProfile | None = None
    selected: bool = Field(description="True for the top entries that make the shortlist.")
    cluster: int | None = Field(
        None, description="Chemotype group; molecules sharing an id are structurally alike."
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="Papers this molecule came from, when found from literature.",
    )


class ShortlistResponse(BaseModel):
    target: Target
    entries: list[ShortlistEntry] = Field(description="Candidates scored, most potent first.")
    shortlist_size: int
    papers_considered: int | None = Field(
        None, description="Papers read, when the candidates came from a literature search."
    )
    dropped: list[DroppedCandidate] = Field(
        default_factory=list, description="Proposed compounds rejected, each with the reason."
    )
    similarity: list[list[float | None]] = Field(
        default_factory=list,
        description="Pairwise Tanimoto similarity between entries, in entry order.",
    )
    chemotypes: int | None = Field(
        None, description="How many distinct chemotypes the scored molecules fall into."
    )
    library_screened: int | None = Field(
        None, description="Compounds searched, when the candidates came from a library screen."
    )
    query_smiles: str | None = Field(
        None, description="The structure the library was screened against."
    )


# --- literature-driven proposal: available on its own endpoint, not in the main flow ---


class Citation(BaseModel):
    id: str = Field(description="Document id from the literature search, e.g. 'pubmed:31666701'.")
    title: str
    source: str
    url: str | None = None
    year: str | None = None


class Candidate(BaseModel):
    name: str = Field(description="Compound name as proposed, resolvable in PubChem.")
    rationale: str = Field(description="Why the literature suggests it inhibits this target.")
    citations: list[Citation] = Field(default_factory=list)


class CandidateProposal(BaseModel):
    target: Target
    candidates: list[Candidate]
    papers_considered: int
    dropped: list[DroppedCandidate] = Field(
        default_factory=list, description="Proposed compounds rejected, each with the reason."
    )
    note: str


ShortlistEntry.model_rebuild()
