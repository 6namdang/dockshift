"""Typed message and evidence contracts (spec 12.3).

Two rules drive every type in this module:

1. A computation that has not been run is never given a numerical placeholder.
   `Metric` therefore carries an explicit `status`, and a non-COMPUTED metric is
   forbidden from carrying a value. Failure never becomes the number zero.
2. Tool status and scientific evidentiary status are distinct. `WorkerState`
   describes whether code ran; `EvidenceState` describes what the result is
   allowed to support.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class WorkerState(str, Enum):
    """Tool-execution status. PENDING -> RUNNING -> terminal."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    UNRESOLVED = "UNRESOLVED"


TERMINAL_STATES = frozenset(
    {WorkerState.SUCCEEDED, WorkerState.FAILED, WorkerState.BLOCKED, WorkerState.UNRESOLVED}
)


class EvidenceState(str, Enum):
    """Scientific standing of an artifact (spec 11).

    An experimental anticancer result is claimed only when a measured assay with
    suitable controls has been supplied and independently reviewed; no code path
    in this repository can promote an artifact to EXPERIMENT_CONFIRMED.
    """

    GENERATED_STRUCTURE = "GENERATED_STRUCTURE"
    COMPUTATIONALLY_EVALUATED = "COMPUTATIONALLY_EVALUATED"
    EXPERIMENT_REQUIRED = "EXPERIMENT_REQUIRED"


class MetricStatus(str, Enum):
    COMPUTED = "COMPUTED"
    NOT_COMPUTED = "NOT_COMPUTED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class Channel(str, Enum):
    """Separated evidence channels (spec 3.2). Never merged or averaged."""

    BEETLE_EXPERIMENTAL = "beetle_experimental"
    QSAR_PREDICTION = "qsar_prediction"
    BEETLE_DOCKING = "beetle_docking"
    HUMAN_DOCKING = "human_docking"
    PREDICTED_COMPLEX = "predicted_complex"
    HUMAN_EXPERIMENTAL = "human_experimental"


class ContractViolation(Exception):
    """Raised when a contract rule would be broken. Never caught into a value."""


@dataclass(frozen=True)
class Metric:
    """A single named quantity with mandatory provenance of its own status.

    A metric with a value must declare the unit it is in and the method that
    produced it. A metric without a COMPUTED status must not carry a value --
    this is what stops an unrun computation from entering the record as 0.0.
    """

    name: str
    status: MetricStatus
    value: float | None = None
    unit: str | None = None
    method: str | None = None

    def __post_init__(self) -> None:
        if self.status is MetricStatus.COMPUTED:
            if self.value is None:
                raise ContractViolation(f"metric {self.name!r}: COMPUTED requires a value")
            if self.unit is None:
                raise ContractViolation(f"metric {self.name!r}: COMPUTED requires a unit")
            if self.method is None:
                raise ContractViolation(f"metric {self.name!r}: COMPUTED requires a method")
            if self.value != self.value or self.value in (float("inf"), float("-inf")):
                raise ContractViolation(f"metric {self.name!r}: non-finite value")
        elif self.value is not None:
            raise ContractViolation(
                f"metric {self.name!r}: status {self.status.value} must not carry a value"
            )

    @classmethod
    def computed(cls, name: str, value: float, unit: str, method: str) -> Metric:
        return cls(name=name, status=MetricStatus.COMPUTED, value=value, unit=unit, method=method)

    @classmethod
    def not_computed(cls, name: str, unit: str | None = None) -> Metric:
        return cls(name=name, status=MetricStatus.NOT_COMPUTED, unit=unit)


#: Repository root, used to keep artifact references portable.
REPO_ROOT = Path(__file__).resolve().parents[3]


def repo_relative(path: str | Path) -> str:
    """Express a path relative to the repository root when possible.

    Absolute paths embed one machine's home directory into the evidence
    record, which makes an artifact reference unusable on any other checkout.
    Paths outside the repository are returned unchanged.
    """
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


@dataclass(frozen=True)
class ArtifactRef:
    """A file on disk plus the digest that makes it citable.

    `path` is stored relative to the repository root so the reference remains
    valid in another checkout of the same commit.
    """

    path: str
    sha256: str
    role: str | None = None

    @classmethod
    def of(cls, path: str | Path, role: str | None = None) -> ArtifactRef:
        p = Path(path)
        if not p.is_file():
            raise ContractViolation(f"artifact {p} does not exist; cannot reference it")
        return cls(path=repo_relative(p), sha256=sha256_file(p), role=role)

    def resolve(self) -> Path:
        """Absolute path for this reference in the current checkout."""
        p = Path(self.path)
        return p if p.is_absolute() else REPO_ROOT / p

    def verify(self) -> bool:
        """True when the file exists and still hashes to the recorded digest."""
        target = self.resolve()
        return target.is_file() and sha256_file(target) == self.sha256


@dataclass(frozen=True)
class AgentEvent:
    """One append-only ledger record (spec 12.3)."""

    run_id: str
    agent: str
    event_type: str
    status: WorkerState
    candidate_id: str | None = None
    target_accession: str | None = None
    input_artifact_hashes: list[str] = field(default_factory=list)
    protocol_id: str | None = None
    outputs: list[ArtifactRef] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    evidence_state: EvidenceState | None = None
    channel: Channel | None = None
    tool_versions: dict[str, str] = field(default_factory=dict)
    error_code: str | None = None
    note: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.status in (WorkerState.FAILED, WorkerState.BLOCKED) and not self.error_code:
            raise ContractViolation(f"{self.agent}: {self.status.value} requires an error_code")
        if self.status is WorkerState.SUCCEEDED and self.error_code:
            raise ContractViolation(f"{self.agent}: SUCCEEDED must not carry an error_code")
        if self.status is not WorkerState.SUCCEEDED:
            bad = [m.name for m in self.metrics if m.status is MetricStatus.COMPUTED]
            if bad:
                raise ContractViolation(
                    f"{self.agent}: non-succeeded event carries COMPUTED metrics {bad}"
                )

    def to_json(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["evidence_state"] = self.evidence_state.value if self.evidence_state else None
        d["channel"] = self.channel.value if self.channel else None
        d["metrics"] = [{**asdict(m), "status": m.status.value} for m in self.metrics]
        return d


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canonical_digest(obj) -> str:
    """Order-independent digest of a JSON-serialisable object."""
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())
