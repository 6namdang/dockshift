"""Inputs to bounded scientific runs. Scientific tool arguments are human supplied."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.structural.models import FileInput, TMAlignRequest

AgentId = Literal["A1", "A2", "A3", "A4", "A5a", "A5b", "A6", "A7"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Target(StrictModel):
    label: str = "hTERT"
    species: str = "Homo sapiens"
    accession: str | None = None
    accession_source: str | None = None
    sequence_sha256: str | None = None
    structure_id: str | None = None
    structure_kind: Literal["experimental", "predicted"] | None = None
    isoform: str | None = None
    verified: bool = False


class RemoteJob(StrictModel):
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    acceptance: dict[str, Any] = Field(default_factory=dict)
    # Poll an existing operation without resubmitting scientific work.
    operation_id: str | None = Field(None, min_length=1, max_length=256)


class MDReview(StrictModel):
    manifest: FileInput
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=200)


class ArtifactBinding(StrictModel):
    """A JSON-pointer selection from a verified upstream typed artifact."""

    step: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    pointer: str = Field(pattern=r"^/")
    argument: str = Field(pattern=r"^/")


class ScientificStep(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    agent: Literal["A2", "A3", "A4", "A5a", "A5b", "A6"]
    branch: Literal["shared", "small_molecule", "biologic"]
    job: RemoteJob
    bindings: list[ArtifactBinding] = Field(default_factory=list, max_length=16)
    # Exact sequences, ligand identity, chain IDs and reference QC are reviewed inputs.
    acceptance: dict[str, Any] = Field(default_factory=dict)
    md_review: MDReview | None = None


class ExecutionBudget(StrictModel):
    # No submission is possible with the default budget, even if a server gate is enabled.
    max_submissions: int = Field(0, ge=0, le=24)
    max_molecules: int = Field(2, ge=1, le=16)
    max_designs: int = Field(1, ge=1, le=8)
    max_md_steps: int = Field(1_000_000, ge=1, le=10_000_000)
    max_llm_calls: int = Field(0, ge=0, le=64)
    max_wall_seconds: int = Field(3600, ge=60, le=86400)
    max_decodes: int = Field(32, ge=2, le=512)
    approved_by: str | None = Field(None, min_length=1, max_length=200)


class RunRequest(StrictModel):
    workflow: Literal["advanced", "candidate", "preparation", "collective"] = "advanced"
    branches: list[Literal["small_molecule", "biologic"]] = Field(
        default_factory=lambda: ["small_molecule", "biologic"], min_length=1, max_length=2
    )
    steps: list[ScientificStep] = Field(default_factory=list, max_length=24)
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget)
    source_run: str | None = Field(None, pattern=r"^agents-[0-9a-f]{32}$")
    resume_only: bool = False
    candidate_name: str = Field("Candidate", min_length=1, max_length=200)
    remote_admet: bool = True
    docking: bool = False
    md_review: MDReview | None = None
    docking_preparation_id: str | None = Field(None, pattern=r"^agents-[0-9a-f]{32}$")
    docking_reviewed_by: str | None = Field(None, min_length=1, max_length=200)
    use_nebius_llm: bool = False
    resume_operations: dict[str, str] = Field(default_factory=dict)
    target: Target = Field(default_factory=Target)
    compounds: list[str] = Field(default_factory=list, max_length=12)
    literature_query: str | None = Field(None, min_length=1, max_length=1000)
    alignment: TMAlignRequest | None = None
    jobs: dict[AgentId, RemoteJob] = Field(default_factory=dict)
    use_local_llm: bool = False
