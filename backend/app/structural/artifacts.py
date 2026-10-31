"""Traversal-safe scientific input and runtime artifact workspaces."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.config import BACKEND_DIR, Settings
from app.structural.errors import ArtifactError
from app.structural.models import ArtifactRef

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class RunWorkspace:
    run_id: str
    path: Path


class ArtifactStore:
    """Own run directories and resolve inputs only beneath dedicated roots."""

    def __init__(self, settings: Settings) -> None:
        self.root = self._create_root(settings.structural_artifact_root, "artifact")
        self.input_root = self._create_root(settings.structural_input_root, "input")
        if self._beneath(self.root, self.input_root) or self._beneath(self.input_root, self.root):
            raise ValueError(
                "STRUCTURAL_ARTIFACT_ROOT and STRUCTURAL_INPUT_ROOT must be separate directories."
            )
        self.allowed_input_roots = (self.root, self.input_root)

    @staticmethod
    def _create_root(configured: Path, label: str) -> Path:
        candidate = configured if configured.is_absolute() else BACKEND_DIR / configured
        candidate = candidate.expanduser()
        if candidate.is_symlink():
            raise ValueError(f"The configured structural {label} root may not be a symlink.")
        candidate.mkdir(mode=0o700, parents=True, exist_ok=True)
        resolved = candidate.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError(f"The configured structural {label} root is not a directory.")
        return resolved

    def create_run(self, operation: str) -> RunWorkspace:
        run_id = str(uuid4())
        operation_name = self.safe_name(operation, fallback="operation")
        path = self.root / run_id / operation_name
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
        return RunWorkspace(run_id=run_id, path=path)

    @staticmethod
    def safe_name(value: str, *, fallback: str = "artifact") -> str:
        cleaned = _SAFE_NAME.sub("_", value.strip()).strip("._")
        return (cleaned or fallback)[:120]

    @staticmethod
    def _beneath(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    def resolve_input(self, reference: str, *, directory: bool = False) -> Path:
        candidate = Path(reference).expanduser()
        candidates = (
            [candidate]
            if candidate.is_absolute()
            else [self.root / candidate, self.input_root / candidate]
        )
        for item in candidates:
            try:
                resolved = item.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not any(self._beneath(resolved, root) for root in self.allowed_input_roots):
                continue
            if directory and resolved.is_dir():
                return resolved
            if not directory and resolved.is_file():
                return resolved
        kind = "directory" if directory else "file"
        raise ArtifactError(
            f"Input {kind} must exist beneath STRUCTURAL_ARTIFACT_ROOT or STRUCTURAL_INPUT_ROOT."
        )

    def resolve_artifact(self, reference: ArtifactRef) -> Path:
        """Resolve an artifact reference strictly beneath the runtime artifact root."""
        candidate = self.root / reference.path
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ArtifactError(
                "Artifact does not exist beneath STRUCTURAL_ARTIFACT_ROOT."
            ) from exc
        if not self._beneath(resolved, self.root) or not resolved.is_file():
            raise ArtifactError("Artifact must be a file beneath STRUCTURAL_ARTIFACT_ROOT.")
        return resolved

    def ref(
        self, path: Path, *, media_type: str | None = None, description: str | None = None
    ) -> ArtifactRef:
        resolved = path.resolve()
        if not self._beneath(resolved, self.root):
            raise ArtifactError("Cannot expose an artifact outside STRUCTURAL_ARTIFACT_ROOT.")
        return ArtifactRef(
            path=resolved.relative_to(self.root).as_posix(),
            media_type=media_type,
            description=description,
        )

    def copy_input(self, source: Path, destination_dir: Path, *, name: str | None = None) -> Path:
        filename = self.safe_name(name or source.name)
        suffix = source.suffix if not Path(filename).suffix else ""
        return self.copy_input_relative(source, destination_dir, f"{filename}{suffix}")

    def copy_input_relative(
        self, source: Path, destination_dir: Path, relative_destination: str
    ) -> Path:
        destination = destination_dir / relative_destination
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination_resolved = destination.resolve()
        if not self._beneath(destination_resolved, self.root):
            raise ArtifactError("Unsafe artifact destination.")
        shutil.copy2(source, destination_resolved)
        return destination_resolved
