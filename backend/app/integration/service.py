"""Run admission, durable progress, restart handling and verified artifact access."""

import asyncio
import hashlib
import json
import re
import threading
from pathlib import Path

from app.config import BACKEND_DIR
from app.nebius.client import NebiusError, NebiusNotConfiguredError

from .llm_provider import configured_provider
from .models import RunRequest
from .privacy import Redactor
from .runtime import SPECS, DockshiftRuntime, new_run_id
from .tools import DockshiftTools, role_tools


class IntegrationService:
    def __init__(self, settings, literature, qsar, structural, nebius):
        self.settings = settings
        self.redact = Redactor(settings)
        self.services = (literature, qsar, structural, nebius)
        path = settings.agent_artifact_root
        self.root = path if path.is_absolute() else BACKEND_DIR / path
        self._lock = asyncio.Lock()
        self._progress_lock = threading.RLock()
        self._tasks = {}
        self._active = set()
        self._demo_started = False

    async def capabilities(self):
        try:
            tools = await self.services[-1].client.list_tools()
            discovered = {t.name: t for t in tools}
            state, error = "reachable", None
        except NebiusNotConfiguredError:
            discovered, state, error = {}, "blocked", "NEBIUS_NOT_CONFIGURED"
        except NebiusError:
            discovered, state, error = {}, "failed", "NEBIUS_DISCOVERY_FAILED"
        return self.redact(
            {
                "nebius": state,
                "error_code": error,
                "compute_enabled": self.settings.agent_compute_enabled,
                "admet_enabled": self.settings.agent_admet_enabled,
                "demo_enabled": self.settings.agent_demo_enabled,
                "demo_started": self._demo_started,
                "demo_source_run": self.settings.agent_demo_source_run,
                "llm": await asyncio.to_thread(configured_provider(self.settings).probe),
                "agents": [
                    {
                        "agent": agent,
                        "tools": [
                            {
                                "name": name,
                                "available": name in discovered,
                                "input_schema": discovered[name].input_schema
                                if name in discovered
                                else None,
                            }
                            for name in names
                        ],
                    }
                    for agent, names in role_tools(self.settings).items()
                ],
            }
        )

    def directory(self, run_id):
        if not re.fullmatch(r"agents-[0-9a-f]{32}", run_id):
            raise FileNotFoundError("Unknown agent run.")
        path = self.root / run_id
        if not path.is_dir():
            raise FileNotFoundError("Unknown agent run.")
        return path

    def _prepare(self, request):
        if self.settings.agent_demo_enabled:
            if request.workflow != "demonstration":
                raise ValueError("This server permits only the bounded demonstration run.")
        if request.workflow == "demonstration":
            if request.source_run != self.settings.agent_demo_source_run:
                raise ValueError(
                    "Demonstration continuation source differs from server authorization."
                )
            if not self.settings.agent_demo_enabled:
                raise ValueError("Bounded demonstration is not enabled on this server.")
            if self.settings.agent_compute_enabled or self.settings.agent_admet_enabled:
                raise ValueError("Demonstration requires scientific computation disabled.")
            if not (request.use_llm and request.llm_provider == "anthropic"):
                raise ValueError("Demonstration requires explicit Claude reasoning.")
            if (
                request.budget.max_llm_calls > 24
                or request.budget.max_llm_cost_usd > 0.10
                or self.settings.anthropic_max_calls > 24
                or self.settings.anthropic_max_cost_usd > 0.10
            ):
                raise ValueError("Demonstration exceeds its request or cost ceiling.")
            with self._progress_lock:
                if self._demo_started:
                    raise ValueError("This one-shot demonstration was already admitted.")
                self._demo_started = True
        if request.workflow == "collective":
            from .collective import audit_plan

            audit_plan(request)
        run_id = new_run_id()
        out = self.root / run_id
        out.mkdir(parents=True, exist_ok=False)
        (out / "request.json").write_text(
            json.dumps(self.redact(request.model_dump(mode="json")), indent=2)
        )
        implementation_root = Path(__file__).parent
        implementation = {
            str(path.relative_to(BACKEND_DIR)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in implementation_root.rglob("*.py")
        }
        (out / "implementation.json").write_text(
            json.dumps(
                {
                    "files_sha256": implementation,
                    "upstream": json.loads(
                        (implementation_root / "scienceclaw" / "SOURCE.json").read_text()
                    ),
                },
                indent=2,
            )
        )
        self._write_progress(
            run_id,
            {
                "run_id": run_id,
                "status": "QUEUED",
                "agents": [
                    {
                        "agent": s.agent_id,
                        "role": s.role,
                        "scientific_status": "PENDING",
                        "detail": "Waiting for execution",
                    }
                    for s in SPECS
                ],
            },
        )
        return run_id

    def _write_progress(self, run_id, data):
        path = self.root / run_id / "progress.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.redact(data), indent=2))
        temp.replace(path)

    def _update(self, run_id, agent=None, status=None, detail=None):
        with self._progress_lock:
            path = self.directory(run_id) / "progress.json"
            data = json.loads(path.read_text())
            if agent:
                row = next(a for a in data["agents"] if a["agent"] == agent)
                row.update(scientific_status=status, detail=detail or "Scientific worker running")
            else:
                data["status"] = status
                if detail:
                    data["detail"] = detail
            self._write_progress(run_id, data)

    async def start(self, request):
        run_id = self._prepare(request)
        task = asyncio.create_task(self._execute(run_id, request), name=run_id)
        self._tasks[run_id] = task
        task.add_done_callback(lambda finished: self._tasks.pop(run_id, None))
        return {"run_id": run_id, "status": "QUEUED"}

    async def run(self, request, provider=None):
        """Compatibility path for callers which explicitly wait for all workers."""
        run_id = self._prepare(request)
        return await self._execute(run_id, request, provider)

    async def _execute(self, run_id, request, provider=None):
        self._active.add(run_id)
        try:
            async with self._lock:
                self._update(run_id, status="RUNNING")
                science = DockshiftTools(
                    self.settings, request, self.directory(run_id), run_id, *self.services
                )
                science.progress = lambda *args: self._update(run_id, *args)
                loop = asyncio.get_running_loop()

                def execute():
                    return DockshiftRuntime(self.root, science, loop, provider=provider).run()

                task = asyncio.create_task(asyncio.to_thread(execute))
                try:
                    report = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
                self._update(run_id, status=report["status"])
                return report
        except Exception:
            self._update(
                run_id, status="FAILED", detail="Run execution failed; no results fabricated."
            )
            # Background exceptions are represented by progress, never left unobserved.
            if run_id not in self._tasks:
                raise
            return None
        finally:
            self._active.discard(run_id)

    async def close(self):
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    def progress(self, run_id):
        path = self.directory(run_id) / "progress.json"
        with self._progress_lock:
            if not path.is_file():
                report = self.report(run_id)  # Support original integration runs.
                return {k: report[k] for k in ("run_id", "status", "agents")}
            data = json.loads(path.read_text())
        if (
            data["status"] in {"RUNNING", "QUEUED"}
            and run_id not in self._active
            and run_id not in self._tasks
        ):
            data.update(
                status="BLOCKED",
                detail="Server restarted during execution. "
                "Resume existing operation IDs; scientific jobs are never replayed automatically.",
            )
        return data

    async def resume(self, run_id):
        if run_id in self._active or run_id in self._tasks:
            raise ValueError("This run is still active.")
        out = self.directory(run_id)
        if (out / "manifest.json").is_file():
            self.report(run_id)
        request = RunRequest.model_validate_json((out / "request.json").read_text())
        if request.workflow not in ("candidate", "collective"):
            raise ValueError("Managed resume supports candidate research runs.")
        operations = {}
        for path in out.glob("*_operation.json"):
            row = json.loads(path.read_text())
            operations[path.name.removesuffix("_operation.json")] = row["operation_id"]
        if not operations:
            raise ValueError("No durable operation was recorded; start a reviewed new run.")
        if request.workflow == "collective":
            return await self.start(
                request.model_copy(
                    update={
                        "resume_operations": operations,
                        "source_run": run_id,
                        "resume_only": True,
                    }
                )
            )
        # Never replay a docking submission during an ADMET-only resume.
        if request.docking and "A5a_diffdock" not in operations:
            raise ValueError(
                "Docking submission not recorded. Review a new request before proceeding."
            )
        return await self.start(request.model_copy(update={"resume_operations": operations}))

    def report(self, run_id):
        directory = self.directory(run_id)
        if not (directory / "report.json").is_file():
            raise FileNotFoundError("Agent report is not complete; use the progress endpoint.")
        manifest = json.loads((directory / "manifest.json").read_text())
        if "report.json" not in manifest:
            raise ValueError("Agent report is absent from the integrity manifest.")
        for name, digest in manifest.items():
            path = directory / name
            if (
                path.parent != directory
                or path.is_symlink()
                or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise ValueError("Agent evidence integrity verification failed.")
        report = json.loads((directory / "report.json").read_text())
        if report.get("workflow") == "collective":
            from .scienceclaw.contracts import ArtifactRef

            for ref in report.get("artifacts", []):
                artifact = ArtifactRef(**{k: ref[k] for k in ("path", "sha256", "role")})
                path = artifact.resolve().resolve()
                if not path.is_relative_to(self.root.resolve()) or not artifact.verify():
                    raise ValueError("Collective handoff integrity verification failed.")
        return report

    def artifact(self, run_id, name):
        self.report(run_id)
        directory = self.directory(run_id)
        manifest = json.loads((directory / "manifest.json").read_text())
        if name not in manifest or Path(name).name != name:
            raise FileNotFoundError("Unknown run artifact.")
        return directory / name
