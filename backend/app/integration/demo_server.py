"""One-shot authenticated local demo server; never enables scientific compute."""

import argparse
import json
import os
import secrets
import uuid
from pathlib import Path

from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import SecretStr

from app.config import BACKEND_DIR, Settings


def create_demo_app(frontend_dir, port, source_run=None):
    import app.main as main
    from app.nebius.client import NebiusClient

    from .scienceclaw.adapters.base import ToolUnavailable

    settings = Settings().model_copy(
        update={
            "agent_demo_enabled": True,
            "agent_demo_source_run": source_run,
            "agent_llm_enabled": True,
            "agent_llm_provider": "anthropic",
            "anthropic_max_calls": 24,
            "anthropic_max_cost_usd": 0.10,
            "anthropic_max_input_tokens": 24000,
            "anthropic_max_output_tokens": 512,
            "agent_compute_enabled": False,
            "agent_admet_enabled": False,
            "structural_rest_enabled": True,
            "mcp_http_enabled": False,
        }
    )
    root = settings.agent_artifact_root
    root = root if root.is_absolute() else BACKEND_DIR / root
    session = root / ("demo-session-" + uuid.uuid4().hex)
    session.mkdir(parents=True, exist_ok=False)
    # A fresh loopback-only demo token; existing application/API keys are not copied.
    token = secrets.token_urlsafe(32)
    settings = settings.model_copy(update={"structural_api_token": SecretStr(token)})
    connection = session / "browser_connection.json"
    descriptor = os.open(connection, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(
            {"url": f"http://127.0.0.1:{port}/ui/", "token": token, "session": str(session)}, handle
        )
    calls = session / "nebius_boundary.jsonl"
    original_call = NebiusClient.call
    original_list = NebiusClient.list_tools

    def record(data):
        with calls.open("a") as handle:
            handle.write(json.dumps(data) + "\n")

    async def read_only_call(self, tool, arguments, **kwargs):
        allowed = tool == "get_model_schema"
        record({"tool": tool, "allowed": allowed, "scientific_submission": False})
        if not allowed:
            raise ToolUnavailable(
                "DEMO_SCIENTIFIC_SUBMISSION_DISABLED",
                "Only read-only model-schema calls are permitted in this demo process.",
            )
        return await original_call(self, tool, arguments, **kwargs)

    async def list_tools(self):
        record({"tool": "list_tools", "allowed": True, "scientific_submission": False})
        return await original_list(self)

    NebiusClient.call = read_only_call
    NebiusClient.list_tools = list_tools
    main.get_settings = lambda: settings
    app = main.create_app()
    app.router.routes = [r for r in app.router.routes if getattr(r, "name", None) != "frontend"]
    app.mount("/ui", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    @app.middleware("http")
    async def no_other_execution(request, call_next):
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and request.url.path != "/api/v1/agents/demonstration"
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "One-shot demo server: other execution routes are disabled."},
            )
        return await call_next(request)

    print("DEMO_CONNECTION_FILE=" + str(connection), flush=True)
    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--continue-run")
    parser.add_argument("--frontend-dir", type=Path, required=True)
    args = parser.parse_args()
    app = create_demo_app(args.frontend_dir, args.port, args.continue_run)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
