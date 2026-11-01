"""Adapter boundary for external scientific tools (spec 12.1).

Every adapter here is a *port*, not an implementation. None of them invents a
result: if the tool, endpoint, licence or binary is absent, the adapter raises
`ToolUnavailable`, the calling agent converts that into a BLOCKED event with an
error code, and the pipeline gate stops. That is the whole point of the layer --
an empty output must never masquerade as a completed computation.

To make this system scientifically useful you implement these ports against
real, pinned software. Until then the honest state is BLOCKED.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


class ToolUnavailable(Exception):
    """External tool, model endpoint or credential is not configured."""

    def __init__(self, error_code: str, detail: str):
        super().__init__(f"{error_code}: {detail}")
        self.error_code = error_code
        self.detail = detail


class ToolFailed(Exception):
    """The tool ran and did not produce a usable result."""

    def __init__(self, error_code: str, detail: str):
        super().__init__(f"{error_code}: {detail}")
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class ToolProbe:
    """What a port reports about its own availability."""

    name: str
    available: bool
    version: str | None
    error_code: str | None = None
    detail: str | None = None


def probe_python_module(module: str, port_name: str, error_code: str) -> ToolProbe:
    try:
        mod = __import__(module)
    except ImportError as exc:
        return ToolProbe(port_name, False, None, error_code, str(exc))
    version = getattr(mod, "__version__", None) or getattr(mod, "version", None)
    return ToolProbe(port_name, True, str(version) if version else "unknown")


def probe_executable(binary: str, port_name: str, error_code: str) -> ToolProbe:
    path = shutil.which(binary)
    if not path:
        return ToolProbe(port_name, False, None, error_code, f"{binary} not on PATH")
    try:
        out = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=20, check=False
        )
        version = (out.stdout or out.stderr).strip().splitlines()[0][:120]
    except (OSError, subprocess.SubprocessError) as exc:
        return ToolProbe(port_name, False, None, error_code, str(exc))
    return ToolProbe(port_name, True, version)


class Adapter:
    """Base port. Subclasses declare `name` and implement `probe`."""

    name: str = "adapter"
    error_code: str = "TOOL_NOT_CONFIGURED"

    def probe(self) -> ToolProbe:  # pragma: no cover - overridden
        raise NotImplementedError

    def require(self) -> ToolProbe:
        probe = self.probe()
        if not probe.available:
            raise ToolUnavailable(
                probe.error_code or self.error_code,
                probe.detail or f"{self.name} is not configured",
            )
        return probe
