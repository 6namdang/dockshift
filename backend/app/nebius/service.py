"""Docking and remote-engine access built on the Nebius MCP client."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.config import Settings
from app.nebius.client import NebiusClient, NebiusError, NebiusNotConfiguredError
from app.nebius.receptor import Site, ensure_receptor, receptor_for, sites

logger = logging.getLogger(__name__)

DIFFDOCK = "infer_diffdock_native"
# Server-enforced bounds, discovered from its own validation errors.
MAX_POSES = 4
MAX_WAIT_SECONDS = 30
# DiffDock's adapter checks this at runtime; fail early with a clear message instead.
MIN_PDB_BYTES = 40
MAX_PDB_BYTES = 2_000_000

# The remote tools worth surfacing as "engines", mapped to the local name they replace.
ENGINE_TOOLS: dict[str, str] = {
    "infer_diffdock_native": "Docking (DiffDock)",
    "submit_alphafold3": "AlphaFold 3",
    "infer_openfold2_native": "OpenFold2",
    "infer_openfold3_native": "OpenFold3",
    "submit_esmfold2": "ESMFold2",
    "submit_gromacs_workflow": "GROMACS",
    "submit_amber_workflow": "AMBER",
    "submit_openmm_workflow": "OpenMM",
    "run_mdprecheck": "MD input check",
    "infer_admet_ai_native": "ADMET-AI",
    "genmol_generate": "Molecule generation (GenMol)",
    "molmim_run_native": "Molecule optimisation (MolMIM)",
}


class RemoteEngine(BaseModel):
    tool: str
    label: str
    available: bool
    description: str = ""


class RemoteEngineStatus(BaseModel):
    configured: bool = Field(description="Whether a Nebius key is present.")
    reachable: bool
    endpoint: str
    total_tools: int = 0
    engines: list[RemoteEngine] = Field(default_factory=list)
    error: str | None = None


class DockedPose(BaseModel):
    rank: int
    confidence: float | None = Field(
        None, description="DiffDock pose confidence. Comparable between poses of one ligand."
    )
    pose: str | None = Field(None, description="Pose structure, when returned inline.")


class DockingResult(BaseModel):
    ligand: str
    poses: list[DockedPose] = Field(default_factory=list)
    best_confidence: float | None = None
    operation_id: str | None = Field(
        None, description="Set when the job is still running; poll it for the result."
    )
    status: str
    note: str
    raw: dict[str, Any] = Field(default_factory=dict, description="The server's own payload.")


class SiteInfo(BaseModel):
    id: str
    name: str
    description: str
    centroid: tuple[float, float, float]


class SiteDocking(BaseModel):
    site: SiteInfo
    ligand: str
    compound: str
    status: str
    best_confidence: float | None = None
    poses: int = 0
    operation_id: str | None = None
    error: str | None = None


class ThreeSiteResult(BaseModel):
    receptor: str = Field(description="PDB entry used as the receptor.")
    compounds: list[str]
    sites: list[SiteInfo]
    runs: list[SiteDocking]
    note: str


class NebiusService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = NebiusClient(settings)

    async def engine_status(self) -> RemoteEngineStatus:
        """Which remote engines are reachable right now."""
        endpoint = self.settings.scientific_models_mcp_url
        if not self.client.configured:
            return RemoteEngineStatus(
                configured=False,
                reachable=False,
                endpoint=endpoint,
                error="No Nebius key configured.",
            )
        try:
            tools = await self.client.list_tools()
        except (NebiusError, NebiusNotConfiguredError) as exc:
            return RemoteEngineStatus(
                configured=True, reachable=False, endpoint=endpoint, error=str(exc)
            )

        by_name = {t.name: t for t in tools}
        engines = [
            RemoteEngine(
                tool=name,
                label=label,
                available=name in by_name,
                description=(
                    by_name[name].description.split("\n")[0][:160] if name in by_name else ""
                ),
            )
            for name, label in ENGINE_TOOLS.items()
        ]
        return RemoteEngineStatus(
            configured=True,
            reachable=True,
            endpoint=endpoint,
            total_tools=len(tools),
            engines=engines,
        )

    async def dock(
        self,
        smiles: str,
        receptor_pdb: str,
        num_poses: int = MAX_POSES,
        wait_seconds: int = MAX_WAIT_SECONDS,
        idempotency_key: str | None = None,
    ) -> DockingResult:
        """Dock one ligand into a receptor with DiffDock.

        ``receptor_pdb`` is the PDB text itself: the adapter takes it inline and rejects
        uploaded paths. Short jobs return poses directly; anything slower comes back with
        an operation id to poll.
        """
        if not smiles.strip():
            raise ValueError("A ligand SMILES is required.")
        size = len(receptor_pdb.encode("utf-8"))
        if size < MIN_PDB_BYTES:
            raise ValueError(f"Receptor PDB is too small ({size} bytes); it needs ATOM records.")
        if size > MAX_PDB_BYTES:
            raise ValueError(
                f"Receptor PDB is {size:,} bytes, over the {MAX_PDB_BYTES:,} limit. "
                "Trim it to the chain or domain being docked."
            )
        if "ATOM" not in receptor_pdb:
            raise ValueError("Receptor PDB contains no ATOM records.")

        arguments: dict[str, Any] = {
            "ligand": smiles.strip(),
            "protein": receptor_pdb,
            "num_poses": max(1, min(num_poses, MAX_POSES)),
            "wait_seconds": max(0, min(wait_seconds, MAX_WAIT_SECONDS)),
        }
        if idempotency_key:
            arguments["idempotency_key"] = idempotency_key

        payload = await self.client.call(DIFFDOCK, arguments)
        return self._read_docking(smiles, payload)

    @staticmethod
    def _read_docking(smiles: str, payload: dict[str, Any]) -> DockingResult:
        """Turn the server's payload into poses, without inventing a score it did not give."""
        payload = _unwrap(payload)
        # A job that is accepted but not yet observed comes back as an error envelope
        # carrying the operation id, with next_action telling you to poll it.
        envelope = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        # An accepted submit nests the id under "operation"; a busy or still-running one
        # answers with an error envelope that carries it instead.
        operation = payload.get("operation") if isinstance(payload.get("operation"), dict) else {}
        operation_id = (
            _first(operation, "id", "operation_id")
            or _first(payload, "operation_id", "operationId")
            or _first(envelope, "operation_id", "operationId")
        )
        status = str(
            _first(operation, "status")
            or _first(payload, "status", "state")
            or _first(envelope, "code", "phase")
            or "unknown"
        )

        poses: list[DockedPose] = []
        raw_poses = _first(payload, "poses", "ranked_poses", "results", "predictions")
        if isinstance(raw_poses, list):
            for i, item in enumerate(raw_poses, start=1):
                if isinstance(item, dict):
                    confidence = _first(item, "confidence", "score", "position_confidence")
                    poses.append(
                        DockedPose(
                            rank=i,
                            confidence=_as_float(confidence),
                            pose=_first(item, "pose", "structure", "sdf", "pdb"),
                        )
                    )
                else:
                    poses.append(DockedPose(rank=i, pose=str(item)[:20000]))

        confidences = [p.confidence for p in poses if p.confidence is not None]
        if poses:
            note = (
                "DiffDock pose confidence ranks poses of this one ligand. Comparing it "
                "between different ligands is close to noise, so do not read it as affinity."
            )
        elif operation_id:
            note = (
                envelope.get("next_action")
                or "Accepted and running. Poll the operation id; do not resubmit."
            )
        else:
            note = "The server returned no poses."

        return DockingResult(
            ligand=smiles,
            poses=poses,
            best_confidence=max(confidences) if confidences else None,
            operation_id=str(operation_id) if operation_id else None,
            status=status,
            note=note,
            raw=payload,
        )

    # --------------------------------------------------------- durable operations
    async def dock_and_wait(
        self,
        smiles: str,
        receptor_pdb: str,
        http: Any,
        num_poses: int = MAX_POSES,
        budget_seconds: float = 420.0,
    ) -> DockingResult:
        """Submit a dock, wait for the operation, and pull the poses out of the artifact.

        The server admits one job at a time and answers a running job with an error
        envelope carrying the operation id, so submission is retried while it reports
        ADMISSION_LIMIT_REACHED rather than being treated as a failure.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + budget_seconds
        result = await self.dock(smiles, receptor_pdb, num_poses=num_poses, wait_seconds=0)
        while "ADMISSION_LIMIT" in result.status.upper():
            if loop.time() > deadline:
                return result
            wait = result.raw.get("error", {}).get("retry_after_seconds") or 60
            logger.info("Admission limit reached; waiting %ss", wait)
            await asyncio.sleep(min(float(wait), 90.0))
            result = await self.dock(smiles, receptor_pdb, num_poses=num_poses, wait_seconds=0)

        if not result.operation_id:
            return result

        final = await self._await_operation(result.operation_id, deadline)
        status = str(
            (final.get("operation") or {}).get("status") or final.get("status") or "unknown"
        )
        artifact = ((final.get("result") or {}).get("artifact") or {}).get("artifact_id")
        if not artifact:
            result.status = status
            await self._acknowledge(result.operation_id)
            return result

        poses, confidences = await self._artifact_poses(artifact, http)
        # The key allows one operation in flight, and a finished one keeps holding the
        # slot until it is acknowledged. Always release it.
        await self._acknowledge(result.operation_id)
        result.poses = [
            DockedPose(rank=i + 1, confidence=c, pose=p)
            for i, (p, c) in enumerate(zip(poses, confidences, strict=False))
        ]
        result.best_confidence = max(confidences) if confidences else None
        result.status = status
        return result

    async def _acknowledge(self, operation_id: str) -> None:
        """Free the concurrency slot. Never let a failure here mask the result."""
        try:
            await self.client.call("acknowledge_operation", {"operation_id": operation_id})
        except Exception as exc:
            logger.warning("Could not acknowledge %s: %s", operation_id, exc)

    async def _await_operation(self, operation_id: str, deadline: float) -> dict[str, Any]:
        """Poll until the operation reaches a terminal state."""
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "ERROR"}
        while True:
            payload = _unwrap(
                await self.client.call("get_operation", {"operation_id": operation_id})
            )
            status = str(
                (payload.get("operation") or {}).get("status") or payload.get("status") or ""
            ).upper()
            if status in terminal or payload.get("done"):
                break
            if asyncio.get_event_loop().time() > deadline:
                break
            await asyncio.sleep(10)
        return _unwrap(
            await self.client.call("get_operation_result", {"operation_id": operation_id})
        )

    async def _artifact_poses(self, artifact_id: str, http: Any) -> tuple[list[str], list[float]]:
        """Download a DiffDock artifact and return its poses and confidences."""
        handle = _unwrap(
            await self.client.call("download_scientific_artifact", {"artifact_id": artifact_id})
        )
        inner = handle.get("handle") or {}
        url = inner.get("url") or handle.get("download_url")
        if not url:
            return [], []
        # The URL is pre-signed and short-lived; it needs no bearer header.
        response = await http.get(url)
        response.raise_for_status()
        data = response.json()
        poses = data.get("ligand_positions") or []
        if isinstance(poses, str):
            poses = [poses]
        confidences = [float(c) for c in (data.get("position_confidence") or []) if c is not None]
        return poses, confidences

    # ------------------------------------------------------- three-site docking
    async def three_site_dock(
        self,
        compounds: dict[str, str],
        radius: float = 18.0,
        wait_seconds: int = MAX_WAIT_SECONDS,
        http: Any = None,
    ) -> ThreeSiteResult:
        """Dock each compound against all three sites on 9Q14.

        ``compounds`` maps a display name to its SMILES. Every ligand is docked against
        the same receptor at three places, so the only thing that varies is the site.
        Which site's scores track measured potency is the question this answers.
        """
        if not compounds:
            raise ValueError("Select at least one compound to dock.")
        if len(compounds) > 8:
            raise ValueError("At most 8 compounds per run.")

        await ensure_receptor(http, self.settings)
        site_list = sites()
        infos = [
            SiteInfo(id=s.id, name=s.name, description=s.description, centroid=s.centroid)
            for s in site_list
        ]
        receptors = {s.id: receptor_for(s.centroid, radius) for s in site_list}

        async def one(site: Site, name: str, smiles: str) -> SiteDocking:
            info = next(i for i in infos if i.id == site.id)
            try:
                result = await self.dock(smiles, receptors[site.id], wait_seconds=wait_seconds)
            except (NebiusError, NebiusNotConfiguredError, ValueError) as exc:
                return SiteDocking(
                    site=info, ligand=smiles, compound=name, status="error", error=str(exc)
                )
            return SiteDocking(
                site=info,
                ligand=smiles,
                compound=name,
                status=result.status,
                best_confidence=result.best_confidence,
                poses=len(result.poses),
                operation_id=result.operation_id,
            )

        # The server admits one job at a time, so these run strictly in sequence.
        runs: list[SiteDocking] = []
        for site in site_list:
            for name, smiles in compounds.items():
                runs.append(await one(site, name, smiles))

        return ThreeSiteResult(
            receptor="9Q14",
            compounds=list(compounds),
            sites=infos,
            runs=runs,
            note=(
                "DiffDock takes no box, so each site is a receptor trimmed around that "
                "centroid. Pose confidence ranks poses of one ligand; it is not an affinity "
                "and is close to noise between different ligands."
            ),
        )

    async def operation(self, operation_id: str) -> dict[str, Any]:
        """Poll a durable operation."""
        return await self.client.call("get_operation", {"operation_id": operation_id})

    async def operation_result(self, operation_id: str) -> dict[str, Any]:
        """Fetch a finished operation's verified result."""
        return await self.client.call("get_operation_result", {"operation_id": operation_id})


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """Some tools answer with a JSON document inside a text block."""
    if set(payload) == {"text"} and isinstance(payload["text"], str):
        try:
            parsed = json.loads(payload["text"])
        except ValueError:
            return payload
        if isinstance(parsed, dict):
            return parsed
    return payload


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group())
    return None
