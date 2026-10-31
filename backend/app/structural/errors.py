"""Typed public failures for structural integrations."""

from __future__ import annotations

from typing import Any


class StructuralError(RuntimeError):
    """A safe, typed failure that REST and MCP callers may inspect."""

    code = "structural_error"
    status_code = 422

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ArtifactError(StructuralError):
    code = "invalid_artifact_reference"


class GeometryError(StructuralError):
    code = "invalid_structural_geometry"


class PrerequisiteError(StructuralError):
    code = "prerequisite_unavailable"
    status_code = 424


class ExecutionFailure(StructuralError):
    code = "external_tool_failed"
    status_code = 502


class ExecutionTimeout(StructuralError):
    code = "external_tool_timeout"
    status_code = 504


class ParseError(StructuralError):
    code = "external_output_invalid"
    status_code = 502
