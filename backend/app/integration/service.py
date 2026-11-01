"""Run admission and durable, hash-verified report access."""

import asyncio
import hashlib
import json
import re
from pathlib import Path

from app.config import BACKEND_DIR
from app.nebius.client import NebiusError, NebiusNotConfiguredError

from .privacy import Redactor
from .runtime import DockshiftRuntime, new_run_id
from .tools import DockshiftTools, role_tools


class IntegrationService:
    def __init__(self, settings, literature, qsar, structural, nebius):
        self.settings = settings
        self.redact = Redactor(settings)
        self.services = (literature, qsar, structural, nebius)
        path = settings.agent_artifact_root
        self.root = path if path.is_absolute() else BACKEND_DIR / path
        self._lock = asyncio.Lock()

    async def capabilities(self):
        nebius = self.services[-1]
        try:
            tools = await nebius.client.list_tools()
            discovered = {t.name: t for t in tools}
            state, error = "reachable", None
        except NebiusNotConfiguredError:
            discovered, state, error = {}, "blocked", "NEBIUS_NOT_CONFIGURED"
        except NebiusError:
            discovered, state, error = {}, "failed", "NEBIUS_DISCOVERY_FAILED"
        return {
            "nebius": state,
            "error_code": error,
            "compute_enabled": self.settings.agent_compute_enabled,
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

    async def run(self, request, provider=None):
        async with self._lock:
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
            science = DockshiftTools(self.settings, request, out, run_id, *self.services)
            loop = asyncio.get_running_loop()

            # Keep the API event loop responsive while the synchronous native runtime
            # talks to its LLM; service calls are scheduled back onto their owning loop.
            def execute():
                return DockshiftRuntime(self.root, science, loop, provider=provider).run()

            task = asyncio.create_task(asyncio.to_thread(execute))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # A disconnected HTTP caller must not free admission while its run is alive.
                await task
                raise

    def report(self, run_id):
        if not re.fullmatch(r"agents-[0-9a-f]{32}", run_id):
            raise FileNotFoundError("Unknown agent run.")
        directory = self.root / run_id
        if not (directory / "report.json").is_file():
            raise FileNotFoundError("Unknown or incomplete agent run.")
        manifest = json.loads((directory / "manifest.json").read_text())
        for name, digest in manifest.items():
            path = directory / name
            if (
                path.parent != directory
                or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise ValueError("Agent evidence integrity verification failed.")
        return json.loads((directory / "report.json").read_text())
