"""FastAPI entrypoint.

    uv run uvicorn app.main:app --reload

REST API under /api/v1, OpenAPI docs at /docs, MCP (Streamable HTTP) at /mcp.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, literature
from app.config import get_settings
from app.literature import literature_service
from app.mcp_server import mcp


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)

    # Build the MCP HTTP app first: its session manager must exist before the lifespan runs.
    mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with literature_service(settings) as service, mcp.session_manager.run():
            app.state.literature_service = service
            yield

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )

    api = APIRouter(prefix="/api/v1")
    api.include_router(literature.router)
    app.include_router(health.router)
    app.include_router(api)

    # Mounted last at the root so FastAPI's own routes win; the MCP app only serves /mcp.
    app.mount("/", mcp_app)
    return app


app = create_app()
