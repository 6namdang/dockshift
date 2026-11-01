"""Inputs to bounded scientific runs. Scientific tool arguments are human supplied."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.structural.models import TMAlignRequest

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
    # Poll an existing operation without resubmitting scientific work.
    operation_id: str | None = Field(None, min_length=1, max_length=256)


class RunRequest(StrictModel):
    target: Target = Field(default_factory=Target)
    compounds: list[str] = Field(default_factory=list, max_length=12)
    literature_query: str | None = Field(None, min_length=1, max_length=1000)
    alignment: TMAlignRequest | None = None
    jobs: dict[AgentId, RemoteJob] = Field(default_factory=dict)
    use_local_llm: bool = False
