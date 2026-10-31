"""Strict schemas shared by structural REST and MCP operations."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

_AF3_MAX_AGGREGATE_TEXT_BYTES = 3_000_000
_AF3_MAX_CANONICAL_REQUEST_BYTES = 3_500_000
_SHA256_PATTERN = r"^[0-9a-f]{64}$"

Seed = Annotated[int, Field(ge=0, le=2_147_483_647)]
SmilesString = Annotated[str, Field(min_length=1, max_length=10_000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RunStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ArtifactRef(StrictModel):
    path: str = Field(
        min_length=1,
        max_length=1024,
        description="Path relative to STRUCTURAL_ARTIFACT_ROOT.",
    )
    media_type: str | None = None
    description: str | None = None


class FileInput(StrictModel):
    path: str = Field(
        min_length=1,
        max_length=1024,
        description=(
            "Path beneath STRUCTURAL_ARTIFACT_ROOT or the dedicated "
            "STRUCTURAL_INPUT_ROOT. Other host paths are rejected."
        ),
    )


class CommandSummary(StrictModel):
    executable: str
    version: str | None = None
    duration_seconds: float = Field(ge=0)
    return_code: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    stdout_log: ArtifactRef | None = None
    stderr_log: ArtifactRef | None = None


class OperationResult(StrictModel):
    run_id: str
    status: RunStatus
    engine: str
    engine_version: str | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    command: CommandSummary | None = None


class ToolCapability(StrictModel):
    tool: str
    configured_value: str | None = None
    available: bool
    resolved_executable: str | None = None
    version: str | None = None
    reason: str | None = None


class CapabilitiesResult(StrictModel):
    status: RunStatus
    artifact_root: str
    execution_backend: str = "local"
    tools: list[ToolCapability]
    notes: list[str] = Field(default_factory=list)


class Vector3(StrictModel):
    x: float
    y: float
    z: float

    def values(self) -> tuple[float, float, float]:
        return self.x, self.y, self.z


class DockingBox(StrictModel):
    center: Vector3
    size: Vector3

    @model_validator(mode="after")
    def validate_size(self) -> DockingBox:
        if any(value <= 0 or value > 80 for value in self.size.values()):
            raise ValueError("Docking-box dimensions must be greater than 0 and at most 80 Å.")
        return self


class TMAlignRequest(StrictModel):
    structure_a: FileInput
    structure_b: FileInput


class RigidTransform(StrictModel):
    rotation: list[list[float]] = Field(description="3x3 rotation matrix.")
    translation: list[float] = Field(description="Translation vector in Å.")

    @model_validator(mode="after")
    def validate_dimensions(self) -> RigidTransform:
        if len(self.rotation) != 3 or any(len(row) != 3 for row in self.rotation):
            raise ValueError("rotation must be a 3x3 matrix")
        if len(self.translation) != 3:
            raise ValueError("translation must contain three values")
        return self


class TMAlignResult(OperationResult):
    aligned_length: int | None = Field(None, ge=0)
    rmsd_angstrom: float | None = Field(None, ge=0)
    sequence_identity: float | None = Field(None, ge=0, le=1)
    tm_score_structure_a: float | None = Field(None, ge=0, le=1)
    tm_score_structure_b: float | None = Field(None, ge=0, le=1)
    transform_a_to_b: RigidTransform | None = None


class AF3Template(StrictModel):
    mmcif: str = Field(min_length=1, max_length=2_000_000)
    query_indices: list[int] = Field(min_length=1, max_length=100_000)
    template_indices: list[int] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def validate_indices(self) -> AF3Template:
        if len(self.query_indices) != len(self.template_indices):
            raise ValueError("query_indices and template_indices must have the same length")
        return self


class AF3Protein(StrictModel):
    sequence: str = Field(min_length=1, max_length=10_000)
    unpaired_msa: str | None = Field(None, max_length=5_000_000)
    paired_msa: str | None = Field(None, max_length=5_000_000)
    templates: list[AF3Template] | None = Field(None, max_length=20)

    @model_validator(mode="after")
    def validate_protein(self) -> AF3Protein:
        sequence = "".join(self.sequence.split()).upper()
        if not sequence.isalpha():
            raise ValueError("Protein sequence may contain letters and whitespace only.")
        if (self.unpaired_msa is None) != (self.paired_msa is None):
            raise ValueError(
                "AlphaFold 3 dialect-v1 requires unpaired_msa and paired_msa "
                "to be supplied together or both omitted."
            )
        self.sequence = sequence
        return self


class AlphaFold3Request(StrictModel):
    job_name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    proteins: list[AF3Protein] = Field(min_length=1, max_length=20)
    ligand_smiles: list[SmilesString] = Field(default_factory=list, max_length=20)
    seeds: list[Seed] = Field(default_factory=lambda: [1], min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_aggregate_size(self) -> AlphaFold3Request:
        text_values: list[str] = [*self.ligand_smiles]
        for protein in self.proteins:
            text_values.append(protein.sequence)
            if protein.unpaired_msa is not None:
                text_values.append(protein.unpaired_msa)
            if protein.paired_msa is not None:
                text_values.append(protein.paired_msa)
            for template in protein.templates or []:
                text_values.append(template.mmcif)
        aggregate = sum(len(value.encode("utf-8")) for value in text_values)
        canonical_size = len(self.model_dump_json().encode("utf-8"))
        if (
            aggregate > _AF3_MAX_AGGREGATE_TEXT_BYTES
            or canonical_size > _AF3_MAX_CANONICAL_REQUEST_BYTES
        ):
            raise ValueError(
                "AlphaFold 3 inline request content is too large. Combined sequences, MSAs, "
                "template mmCIF, ligand strings, and request metadata must remain below the "
                "3 MB inline budget. Omit large MSAs/templates for AF3 data-pipeline generation; "
                "a future file-backed interface is required for staged inputs."
            )
        return self


class AlphaFold3Result(OperationResult):
    input_json: ArtifactRef
    top_ranked_structure: ArtifactRef
    structure_artifacts: list[ArtifactRef] = Field(default_factory=list)
    confidence_artifacts: list[ArtifactRef] = Field(default_factory=list)
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class LigandPreparationRequest(StrictModel):
    name: str = Field(default="ligand", min_length=1, max_length=80)
    smiles: str | None = Field(None, min_length=1, max_length=10_000)
    sdf: FileInput | None = None
    random_seed: int = Field(61453, ge=0, le=2_147_483_647)
    optimize: bool = True

    @model_validator(mode="after")
    def exactly_one_source(self) -> LigandPreparationRequest:
        if (self.smiles is None) == (self.sdf is None):
            raise ValueError("Provide exactly one of smiles or sdf.")
        return self


class LigandPreparationResult(OperationResult):
    name: str
    canonical_smiles: str
    force_field: str | None = None
    sdf: ArtifactRef
    pdb: ArtifactRef
    pdbqt: ArtifactRef


class ReceptorPreparationRequest(StrictModel):
    structure: FileInput
    remove_waters: bool = True
    remove_heterogens: bool = False
    remove_alternate_locations: bool = True


class ReceptorPreparationResult(OperationResult):
    cleaned_structure: ArtifactRef
    pdbqt: ArtifactRef


class FPocketRequest(StrictModel):
    structure: FileInput


class Pocket(StrictModel):
    pocket_id: int = Field(ge=1)
    center: Vector3
    minimum: Vector3
    maximum: Vector3
    atom_coordinates: list[Vector3] = Field(default_factory=list, max_length=50_000)
    residue_ids: list[str] = Field(default_factory=list)
    score: float | None = None
    druggability_score: float | None = None
    volume_angstrom3: float | None = Field(None, ge=0)
    artifact: ArtifactRef | None = None


class FPocketResult(OperationResult):
    pockets: list[Pocket] = Field(default_factory=list)


class PocketComparisonRequest(StrictModel):
    moving_pocket: Pocket
    reference_pocket: Pocket
    moving_to_reference: RigidTransform
    overlap_threshold_angstrom: float = Field(2.0, gt=0, le=10)


class PocketComparisonResult(StrictModel):
    transformed_centroid_distance_angstrom: float = Field(ge=0)
    nearest_neighbor_overlap: float = Field(ge=0, le=1)
    size_ratio: float = Field(ge=0, le=1)
    volume_ratio: float | None = Field(None, ge=0, le=1)
    composite_similarity: float = Field(ge=0, le=1)
    formula: str
    warning: str


class PocketBoxRequest(StrictModel):
    pocket: Pocket
    padding_angstrom: float = Field(4.0, ge=0, le=20)
    max_size_angstrom: float = Field(40.0, gt=0, le=80)


class DockingRequest(StrictModel):
    receptor_pdbqt: FileInput
    ligand_pdbqt: FileInput
    box: DockingBox
    exhaustiveness: int = Field(8, ge=1, le=128)
    num_modes: int = Field(9, ge=1, le=50)
    energy_range: float = Field(3.0, ge=0, le=20)
    seed: int | None = Field(None, ge=0, le=2_147_483_647)


class DockingMode(StrictModel):
    rank: int = Field(ge=1)
    affinity_kcal_mol: float
    rmsd_lower_bound_angstrom: float | None = Field(None, ge=0)
    rmsd_upper_bound_angstrom: float | None = Field(None, ge=0)


class DockingResult(OperationResult):
    modes: list[DockingMode] = Field(min_length=1)
    pose: ArtifactRef
    md_ready: bool = False
    md_prerequisites: list[str] = Field(default_factory=list)


class GromacsInclude(StrictModel):
    source: FileInput
    destination: str = Field(
        min_length=1,
        max_length=1024,
        description="Relative POSIX path to preserve beneath the staged GROMACS bundle.",
    )

    @model_validator(mode="after")
    def validate_destination(self) -> GromacsInclude:
        if "\\" in self.destination:
            raise ValueError("GROMACS include destination must use forward slashes.")
        path = PurePosixPath(self.destination)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(
                "GROMACS include destination must be a normalized relative path without traversal."
            )
        self.destination = path.as_posix()
        return self


class GromacsSystemBundle(StrictModel):
    coordinate: FileInput
    topology: FileInput
    includes: list[GromacsInclude] = Field(default_factory=list, max_length=100)
    index: FileInput | None = None


class GromacsMdpBundle(StrictModel):
    em: FileInput
    nvt: FileInput
    npt: FileInput
    md: FileInput


class LiteratureCheckpoint(StrictModel):
    completed: bool = False
    references: list[str] = Field(default_factory=list, max_length=100)
    notes: str | None = Field(None, max_length=10_000)


class GromacsRequest(StrictModel):
    system: GromacsSystemBundle
    mdp: GromacsMdpBundle
    maxwarn: int = Field(0, ge=0, le=10)
    threads: int | None = Field(None, ge=1, le=256)


class GromacsStageResult(StrictModel):
    stage: str
    status: RunStatus
    tpr: ArtifactRef | None = None
    coordinate: ArtifactRef | None = None
    trajectory: ArtifactRef | None = None
    checkpoint: ArtifactRef | None = None
    energy: ArtifactRef | None = None
    log: ArtifactRef | None = None
    commands: list[CommandSummary] = Field(default_factory=list)
    error: str | None = None
    failure_details: dict[str, Any] = Field(default_factory=dict)


class GromacsResult(OperationResult):
    stages: list[GromacsStageResult] = Field(default_factory=list)


class CandidateLigand(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=100)
    smiles: str | None = Field(None, min_length=1, max_length=10_000)
    sdf: FileInput | None = None
    qsar_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def exactly_one_source(self) -> CandidateLigand:
        if (self.smiles is None) == (self.sdf is None):
            raise ValueError("Each candidate requires exactly one of smiles or sdf.")
        return self


class PocketPlanRequest(StrictModel):
    tctert_structure: FileInput
    htert_structure: FileInput
    tctert_pocket: Pocket
    htert_pocket: Pocket
    proposed_tctert_box: DockingBox
    proposed_htert_box: DockingBox
    alignment: TMAlignResult | None = None
    moving_to_reference: RigidTransform | None = None
    overlap_threshold_angstrom: float = Field(2.0, gt=0, le=10)

    @model_validator(mode="after")
    def exactly_one_transform_source(self) -> PocketPlanRequest:
        if (self.alignment is None) == (self.moving_to_reference is None):
            raise ValueError("Provide exactly one of alignment or moving_to_reference.")
        if self.alignment is not None and self.alignment.transform_a_to_b is None:
            raise ValueError("The supplied TM-align result must contain transform_a_to_b.")
        return self

    def transform(self) -> RigidTransform:
        if self.moving_to_reference is not None:
            return self.moving_to_reference
        assert self.alignment is not None and self.alignment.transform_a_to_b is not None
        return self.alignment.transform_a_to_b


class PocketPlanDocument(StrictModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    tctert_structure: FileInput
    htert_structure: FileInput
    tctert_structure_sha256: str = Field(pattern=_SHA256_PATTERN)
    htert_structure_sha256: str = Field(pattern=_SHA256_PATTERN)
    transform_tctert_to_htert: RigidTransform
    selected_tctert_pocket: Pocket
    selected_htert_pocket: Pocket
    tctert_docking_box: DockingBox
    htert_docking_box: DockingBox
    pocket_comparison: PocketComparisonResult


class PocketPlanResult(OperationResult):
    proposal_artifact: ArtifactRef
    proposal_sha256: str = Field(pattern=_SHA256_PATTERN)
    selected_tctert_pocket_id: int = Field(ge=1)
    selected_htert_pocket_id: int = Field(ge=1)
    tctert_structure_sha256: str = Field(pattern=_SHA256_PATTERN)
    htert_structure_sha256: str = Field(pattern=_SHA256_PATTERN)
    transform_tctert_to_htert: RigidTransform
    selected_tctert_pocket: Pocket
    selected_htert_pocket: Pocket
    tctert_docking_box: DockingBox
    htert_docking_box: DockingBox
    pocket_comparison: PocketComparisonResult


class PocketApproval(StrictModel):
    proposal_artifact: ArtifactRef
    proposal_sha256: str = Field(pattern=_SHA256_PATTERN)
    approved_by: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def validate_review_text(self) -> PocketApproval:
        if not self.approved_by.strip():
            raise ValueError("Pocket approval requires a nonblank approved_by value.")
        if not self.rationale.strip():
            raise ValueError("Pocket approval requires a nonblank rationale.")
        self.approved_by = self.approved_by.strip()
        self.rationale = self.rationale.strip()
        return self


class StructuralWorkflowRequest(StrictModel):
    tctert_structure: FileInput
    htert_structure: FileInput
    candidates: list[CandidateLigand] = Field(min_length=1, max_length=6)
    pocket_approval: PocketApproval
    docking_exhaustiveness: int = Field(8, ge=1, le=128)
    docking_num_modes: int = Field(9, ge=1, le=50)
    docking_seed: int | None = Field(None, ge=0, le=2_147_483_647)
    after_qsar_literature_checkpoint: LiteratureCheckpoint

    @model_validator(mode="after")
    def validate_workflow_gates(self) -> StructuralWorkflowRequest:
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate_id values must be unique")
        checkpoint = self.after_qsar_literature_checkpoint
        if not checkpoint.completed:
            raise ValueError("The post-QSAR literature checkpoint must be completed.")
        if not checkpoint.references or not all(item.strip() for item in checkpoint.references):
            raise ValueError(
                "The post-QSAR literature checkpoint requires at least one nonblank reference."
            )
        if checkpoint.notes is None or not checkpoint.notes.strip():
            raise ValueError("The post-QSAR literature checkpoint requires nonblank notes.")
        return self


class WorkflowCandidateResult(StrictModel):
    candidate_id: str
    status: RunStatus
    submitted_smiles: str | None = None
    submitted_sdf_path: str | None = None
    submitted_sdf_artifact: ArtifactRef | None = None
    submitted_sdf_sha256: str | None = Field(None, pattern=_SHA256_PATTERN)
    preparation: LigandPreparationResult | None = None
    tctert_docking: DockingResult | None = None
    htert_docking: DockingResult | None = None
    best_affinity_kcal_mol: float | None = Field(
        None, description="Best hTERT-pocket Vina score used for workflow ranking."
    )
    conformer_seed: int = Field(ge=0, le=2_147_483_647)
    vina_seed: int | None = Field(None, ge=0, le=2_147_483_647)
    failed_stage: str | None = None
    error: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)
    qsar_metadata: dict[str, Any] = Field(default_factory=dict)


class StructuralWorkflowResult(OperationResult):
    preflight: CapabilitiesResult
    pocket_plan_artifact: ArtifactRef | None = None
    pocket_plan_sha256: str | None = Field(None, pattern=_SHA256_PATTERN)
    approved_transform_tctert_to_htert: RigidTransform | None = None
    selected_tctert_pocket: Pocket | None = None
    selected_htert_pocket: Pocket | None = None
    selected_tctert_pocket_id: int | None = None
    selected_htert_pocket_id: int | None = None
    pocket_comparison: PocketComparisonResult | None = None
    tctert_docking_box: DockingBox | None = None
    htert_docking_box: DockingBox | None = None
    tctert_receptor_preparation: ReceptorPreparationResult | None = None
    htert_receptor_preparation: ReceptorPreparationResult | None = None
    candidates: list[WorkflowCandidateResult] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)
    literature_checkpoint: LiteratureCheckpoint | None = None
    md_next_step: str
