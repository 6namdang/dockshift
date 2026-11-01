"""Typed envelope for model-validated, hash-addressed scientific handoffs."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import AgentId, StrictModel

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ScientificPayload(BaseModel):
    # Native model-specific fields are retained, while the envelope is stable.
    # Their scientific validation belongs to the model-specific output adapters.
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    kind: Literal[
        "target", "molecules", "sequences", "structure", "complex", "backbone", "docking", "md"
    ]
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


class ScientificArtifact(StrictModel):
    schema_version: Literal["dockshift-scientific-artifact/v1"] = Field(alias="schema")
    step: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    agent: AgentId
    branch: Literal["shared", "small_molecule", "biologic"]
    provider: Literal["nebius", "rcsb", "uniprot"]
    data: ScientificPayload
    input_sha256: list[Digest]


def encode_artifact(record: dict[str, Any]):
    return ScientificArtifact.model_validate(record).model_dump(mode="json", by_alias=True)
