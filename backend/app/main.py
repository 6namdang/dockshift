"""FastAPI entrypoint.

    uv run uvicorn app.main:app --reload

REST API lives under /api/v1. HTTP MCP at /mcp is separately opt-in and authenticated.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent import PipelineService
from app.api.routes import health, literature, pipeline, qsar, structural
from app.config import BACKEND_DIR, get_settings
from app.literature import LiteratureSearchService
from app.literature.http import build_http_client
from app.mcp_server import create_mcp_http_app, mcp
from app.qsar import QsarService
from app.structural import StructuralService


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    mcp_app = create_mcp_http_app(settings) if settings.mcp_http_enabled else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(build_http_client(settings))
            if mcp_app is not None:
                await stack.enter_async_context(mcp.session_manager.run())
            literature_service = LiteratureSearchService(client, settings)
            qsar_service = QsarService(client, settings)
            app.state.literature_service = literature_service
            app.state.qsar_service = qsar_service
            app.state.pipeline_service = PipelineService(
                client, literature_service, qsar_service, settings
            )
            app.state.structural_service = StructuralService(settings)
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
    api.include_router(structural.router)
    app.include_router(health.router)
    app.include_router(api)

    frontend = BACKEND_DIR.parent / "frontend"
    if (frontend / "index.html").is_file():
        app.mount("/ui", StaticFiles(directory=frontend, html=True), name="frontend")

    if mcp_app is not None:
        # Mounted last so FastAPI routes win; the authenticated MCP app only serves /mcp.
        app.mount("/", mcp_app)
    return app


app = create_app()
