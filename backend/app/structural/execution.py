"""Bounded, shell-free execution of configured scientific engines."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from app.structural.artifacts import ArtifactStore, RunWorkspace
from app.structural.errors import ExecutionFailure, ExecutionTimeout, PrerequisiteError
from app.structural.models import CommandSummary

_TAIL_BYTES = 16_384
_CAPTURE_BYTES = 1_000_000
_TERMINATION_GRACE_SECONDS = 3.0
_DRAIN_GRACE_SECONDS = 1.0
_TRUNCATION_MARKER = b"\n[Dockshift log truncated at configured byte limit]\n"
_DrainT = TypeVar("_DrainT")


@dataclass(frozen=True)
class ExecutionOutput:
    argv: tuple[str, ...]
    stdout: str
    stderr: str
    summary: CommandSummary


class ExecutionBackend(ABC):
    """Backend boundary for deployments; only local execution is implemented."""

    @abstractmethod
    async def run(
        self,
        executable: str,
        arguments: list[str],
        workspace: RunWorkspace,
        *,
        label: str,
        timeout_seconds: float | None = None,
        check: bool = True,
    ) -> ExecutionOutput: ...


def _resolve_executable(configured: str) -> str | None:
    resolved = shutil.which(configured)
    if resolved is not None:
        return resolved
    path = Path(configured).expanduser()
    if path.is_file() and os.access(path, os.X_OK):
        return str(path.resolve())
    return None


def _append_tail(tail: bytearray, chunk: bytes) -> None:
    tail.extend(chunk)
    if len(tail) > _TAIL_BYTES:
        del tail[:-_TAIL_BYTES]


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_process_group_exit(process_group_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while _process_group_exists(process_group_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not _process_group_exists(process_group_id)


def _leader_is_running(process: asyncio.subprocess.Process) -> bool:
    if process.returncode is not None:
        return False
    stat_path = Path(f"/proc/{process.pid}/stat")
    try:
        state = stat_path.read_text(encoding="utf-8").split()[2]
    except IndexError:
        return False
    except OSError:
        if Path("/proc").is_dir():
            return False
        try:
            os.kill(process.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    return state != "Z"


async def _wait_for_leader_exit(
    process: asyncio.subprocess.Process, duration_seconds: float
) -> bool:
    """Return True on timeout, even when descendants keep inherited pipes open."""
    waiter = asyncio.create_task(process.wait())
    deadline = time.monotonic() + duration_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        done, _ = await asyncio.wait({waiter}, timeout=min(0.05, remaining))
        if done or not _leader_is_running(process):
            return False


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    """Terminate the complete child process group, independently of leader state."""
    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        pass

    group_exited = await asyncio.to_thread(
        _wait_for_process_group_exit,
        process_group_id,
        _TERMINATION_GRACE_SECONDS,
    )

    if not group_exited:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        await asyncio.wait_for(process.wait(), timeout=_DRAIN_GRACE_SECONDS)
    except TimeoutError:
        # SIGKILL was already sent to the process group. Never let cleanup hang the caller.
        pass

    await asyncio.to_thread(
        _wait_for_process_group_exit,
        process_group_id,
        _DRAIN_GRACE_SECONDS,
    )


async def _finish_tasks(
    tasks: tuple[asyncio.Task[_DrainT], ...],
) -> tuple[_DrainT | BaseException, ...]:
    try:
        return tuple(
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=_DRAIN_GRACE_SECONDS,
            )
        )
    except TimeoutError:
        for task in tasks:
            if not task.done():
                task.cancel()
        return tuple(await asyncio.gather(*tasks, return_exceptions=True))


async def _drain_pipe(
    stream: asyncio.StreamReader,
    path: Path,
    max_log_bytes: int,
) -> tuple[str, str]:
    captured = bytearray()
    tail = bytearray()
    written = 0
    truncated = False
    with path.open("wb") as log:
        while True:
            chunk = await stream.read(65_536)
            if not chunk:
                break
            _append_tail(tail, chunk)
            if len(captured) < _CAPTURE_BYTES:
                captured.extend(chunk[: _CAPTURE_BYTES - len(captured)])
            remaining = max_log_bytes - written
            if remaining > 0:
                piece = chunk[:remaining]
                log.write(piece)
                log.flush()
                written += len(piece)
            if len(chunk) > remaining:
                truncated = True
        if truncated:
            marker_start = max(max_log_bytes - len(_TRUNCATION_MARKER), 0)
            log.seek(marker_start)
            log.write(_TRUNCATION_MARKER[-max_log_bytes:])
            log.truncate(max_log_bytes)
    return (
        captured.decode("utf-8", errors="replace"),
        tail.decode("utf-8", errors="replace"),
    )


async def _drain_capture(stream: asyncio.StreamReader) -> bytes:
    captured = bytearray()
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            break
        if len(captured) < _TAIL_BYTES:
            captured.extend(chunk[: _TAIL_BYTES - len(captured)])
    return bytes(captured)


class LocalExecutionBackend(ExecutionBackend):
    def __init__(self, store: ArtifactStore, timeout_seconds: float, max_log_bytes: int) -> None:
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.max_log_bytes = max_log_bytes

    @staticmethod
    def resolve_executable(configured: str, tool: str) -> str:
        resolved = _resolve_executable(configured)
        if resolved is None:
            raise PrerequisiteError(
                f"{tool} executable is unavailable. Configure its Settings/environment path.",
                details={"tool": tool},
            )
        return resolved

    async def run(
        self,
        executable: str,
        arguments: list[str],
        workspace: RunWorkspace,
        *,
        label: str,
        timeout_seconds: float | None = None,
        check: bool = True,
    ) -> ExecutionOutput:
        resolved = self.resolve_executable(executable, label)
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        started = time.monotonic()
        stem = self.store.safe_name(label)
        stdout_path = workspace.path / f"{stem}.stdout.log"
        stderr_path = workspace.path / f"{stem}.stderr.log"
        process = await asyncio.create_subprocess_exec(
            resolved,
            *arguments,
            cwd=workspace.path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None and process.stderr is not None
        stdout_task = asyncio.create_task(
            _drain_pipe(process.stdout, stdout_path, self.max_log_bytes)
        )
        stderr_task = asyncio.create_task(
            _drain_pipe(process.stderr, stderr_path, self.max_log_bytes)
        )
        tasks = (stdout_task, stderr_task)
        timed_out = False
        try:
            timed_out = await _wait_for_leader_exit(process, timeout)
        except asyncio.CancelledError:
            await asyncio.shield(_terminate_process_group(process))
            await asyncio.shield(_finish_tasks(tasks))
            raise
        await asyncio.shield(_terminate_process_group(process))
        drained = await asyncio.shield(_finish_tasks(tasks))
        drain_ok = all(isinstance(item, tuple) for item in drained)
        stdout_result = drained[0] if isinstance(drained[0], tuple) else ("", "")
        stderr_result = drained[1] if isinstance(drained[1], tuple) else ("", "")
        stdout, stdout_tail = stdout_result
        stderr, stderr_tail = stderr_result
        summary = self._summary(
            resolved,
            workspace,
            started,
            process.returncode if process.returncode is not None else -9,
            stdout_path,
            stderr_path,
            stdout_tail,
            stderr_tail,
        )
        if timed_out:
            raise ExecutionTimeout(
                f"{label} exceeded the configured {timeout:g}-second timeout.",
                details={
                    "tool": label,
                    "timeout_seconds": timeout,
                    "stdout_log": summary.stdout_log.model_dump(mode="json"),
                    "stderr_log": summary.stderr_log.model_dump(mode="json"),
                    "drain_incomplete": not drain_ok,
                },
            )
        if not drain_ok:
            raise ExecutionFailure(
                f"{label} output streams could not be drained safely.",
                details={
                    "tool": label,
                    "stdout_log": summary.stdout_log.model_dump(mode="json"),
                    "stderr_log": summary.stderr_log.model_dump(mode="json"),
                },
            )
        if check and process.returncode != 0:
            raise ExecutionFailure(
                f"{label} exited with code {process.returncode}.",
                details={
                    "tool": label,
                    "return_code": process.returncode,
                    "stdout_log": summary.stdout_log.model_dump(mode="json"),
                    "stderr_log": summary.stderr_log.model_dump(mode="json"),
                },
            )
        return ExecutionOutput(tuple([resolved, *arguments]), stdout, stderr, summary)

    def _summary(
        self,
        resolved: str,
        workspace: RunWorkspace,
        started: float,
        return_code: int,
        stdout_path: Path,
        stderr_path: Path,
        stdout_tail: str,
        stderr_tail: str,
    ) -> CommandSummary:
        return CommandSummary(
            executable=Path(resolved).name,
            duration_seconds=round(time.monotonic() - started, 3),
            return_code=return_code,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            stdout_log=self.store.ref(stdout_path, media_type="text/plain"),
            stderr_log=self.store.ref(stderr_path, media_type="text/plain"),
        )


async def probe_version(executable: str, arguments: list[str]) -> tuple[str | None, str | None]:
    """Return resolved executable and a short version line without raising."""
    resolved = _resolve_executable(executable)
    if resolved is None:
        return None, None
    process: asyncio.subprocess.Process | None = None
    tasks: tuple[asyncio.Task[bytes], asyncio.Task[bytes]] | None = None
    timed_out = False
    try:
        process = await asyncio.create_subprocess_exec(
            resolved,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None and process.stderr is not None
        tasks = (
            asyncio.create_task(_drain_capture(process.stdout)),
            asyncio.create_task(_drain_capture(process.stderr)),
        )
        timed_out = await _wait_for_leader_exit(process, 5)
        await asyncio.shield(_terminate_process_group(process))
        drained = await asyncio.shield(_finish_tasks(tasks))
    except asyncio.CancelledError:
        if process is not None:
            await asyncio.shield(_terminate_process_group(process))
        if tasks is not None:
            await asyncio.shield(_finish_tasks(tasks))
        raise
    except OSError:
        if process is not None:
            await asyncio.shield(_terminate_process_group(process))
        if tasks is not None:
            await asyncio.shield(_finish_tasks(tasks))
        return resolved, None
    if timed_out or not all(isinstance(item, bytes) for item in drained):
        return resolved, None
    stdout, stderr = drained
    text = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
    line = next((line.strip() for line in text.splitlines() if line.strip()), None)
    return resolved, line[:300] if line else None
