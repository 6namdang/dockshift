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
from fastapi.staticfiles import StaticFiles

from app.agent import PipelineService
from app.api.routes import health, literature, pipeline, qsar
from app.config import BACKEND_DIR, get_settings
from app.literature import LiteratureSearchService
from app.literature.http import build_http_client
from app.mcp_server import mcp
from app.qsar import QsarService


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)

    # Build the MCP HTTP app first: its session manager must exist before the lifespan runs.
    mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with build_http_client(settings) as client, mcp.session_manager.run():
            literature_service = LiteratureSearchService(client, settings)
            qsar_service = QsarService(client, settings)
            app.state.literature_service = literature_service
            app.state.qsar_service = qsar_service
            app.state.pipeline_service = PipelineService(
                client, literature_service, qsar_service, settings
            )
            yield

    app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
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
    api.include_router(qsar.router)
    api.include_router(pipeline.router)
    app.include_router(health.router)
    app.include_router(api)

    # The frontend, served same-origin at /ui so it needs no CORS exemption.
    frontend = BACKEND_DIR.parent / "frontend"
    if (frontend / "index.html").is_file():
        app.mount("/ui", StaticFiles(directory=frontend, html=True), name="frontend")

    # Mounted last at the root so FastAPI's own routes win; the MCP app only serves /mcp.
    app.mount("/", mcp_app)
    return app


app = create_app()
