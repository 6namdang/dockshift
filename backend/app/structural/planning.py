"""Immutable, digest-bound pocket planning artifacts."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

from pydantic import ValidationError

from app.structural.artifacts import ArtifactStore
from app.structural.errors import ArtifactError
from app.structural.models import (
    ArtifactRef,
    FileInput,
    PocketApproval,
    PocketComparisonRequest,
    PocketPlanDocument,
    PocketPlanRequest,
    PocketPlanResult,
    RunStatus,
)
from app.structural.pockets import compare_pockets


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(document: PocketPlanDocument) -> bytes:
    payload = json.dumps(
        document.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{payload}\n".encode()


class PocketPlanStore:
    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    def create(self, request: PocketPlanRequest) -> PocketPlanResult:
        workspace = self.store.create_run("pocket-plan")
        tctert_path = self.store.resolve_input(request.tctert_structure.path)
        htert_path = self.store.resolve_input(request.htert_structure.path)
        transform = request.transform()
        comparison = compare_pockets(
            PocketComparisonRequest(
                moving_pocket=request.tctert_pocket,
                reference_pocket=request.htert_pocket,
                moving_to_reference=transform,
                overlap_threshold_angstrom=request.overlap_threshold_angstrom,
            )
        )
        document = PocketPlanDocument(
            tctert_structure=request.tctert_structure,
            htert_structure=request.htert_structure,
            tctert_structure_sha256=sha256_file(tctert_path),
            htert_structure_sha256=sha256_file(htert_path),
            transform_tctert_to_htert=transform,
            selected_tctert_pocket=request.tctert_pocket,
            selected_htert_pocket=request.htert_pocket,
            tctert_docking_box=request.proposed_tctert_box,
            htert_docking_box=request.proposed_htert_box,
            pocket_comparison=comparison,
        )
        proposal_path = workspace.path / "pocket-proposal.json"
        content = _canonical_bytes(document)
        proposal_path.write_bytes(content)
        proposal_ref = self.store.ref(
            proposal_path,
            media_type="application/json",
            description="Immutable canonical pocket proposal",
        )
        digest = hashlib.sha256(content).hexdigest()
        return self._result(workspace.run_id, proposal_ref, digest, document)

    def load_verified(
        self,
        approval: PocketApproval,
        tctert_structure: FileInput,
        htert_structure: FileInput,
    ) -> PocketPlanDocument:
        proposal_path = self.store.resolve_artifact(approval.proposal_artifact)
        content = proposal_path.read_bytes()
        actual_digest = hashlib.sha256(content).hexdigest()
        if not secrets.compare_digest(actual_digest, approval.proposal_sha256):
            raise ArtifactError(
                "Pocket proposal digest does not match the approved SHA-256.",
                details={"proposal_artifact": approval.proposal_artifact.path},
            )
        try:
            payload = json.loads(content)
            document = PocketPlanDocument.model_validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
            raise ArtifactError("Pocket proposal is not valid canonical proposal JSON.") from exc
        if content != _canonical_bytes(document):
            raise ArtifactError("Pocket proposal is not in the required canonical JSON form.")
        if (
            document.tctert_structure != tctert_structure
            or document.htert_structure != htert_structure
        ):
            raise ArtifactError(
                "Workflow structure references do not exactly match the approved pocket proposal."
            )
        current_tctert = sha256_file(self.store.resolve_input(tctert_structure.path))
        current_htert = sha256_file(self.store.resolve_input(htert_structure.path))
        if not secrets.compare_digest(current_tctert, document.tctert_structure_sha256):
            raise ArtifactError("The current tcTERT structure differs from the approved proposal.")
        if not secrets.compare_digest(current_htert, document.htert_structure_sha256):
            raise ArtifactError("The current hTERT structure differs from the approved proposal.")
        return document

    @staticmethod
    def _result(
        run_id: str,
        proposal_artifact: ArtifactRef,
        proposal_sha256: str,
        document: PocketPlanDocument,
    ) -> PocketPlanResult:
        return PocketPlanResult(
            run_id=run_id,
            status=RunStatus.SUCCESS,
            engine="Dockshift immutable pocket planner",
            artifacts=[proposal_artifact],
            provenance={"schema_version": document.schema_version},
            proposal_artifact=proposal_artifact,
            proposal_sha256=proposal_sha256,
            selected_tctert_pocket_id=document.selected_tctert_pocket.pocket_id,
            selected_htert_pocket_id=document.selected_htert_pocket.pocket_id,
            tctert_structure_sha256=document.tctert_structure_sha256,
            htert_structure_sha256=document.htert_structure_sha256,
            transform_tctert_to_htert=document.transform_tctert_to_htert,
            selected_tctert_pocket=document.selected_tctert_pocket,
            selected_htert_pocket=document.selected_htert_pocket,
            tctert_docking_box=document.tctert_docking_box,
            htert_docking_box=document.htert_docking_box,
            pocket_comparison=document.pocket_comparison,
        )
