"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.agent import PipelineService
from app.literature import LiteratureSearchService
from app.qsar import QsarService


def get_literature_service(request: Request) -> LiteratureSearchService:
    return request.app.state.literature_service


def get_qsar_service(request: Request) -> QsarService:
    return request.app.state.qsar_service


def get_pipeline_service(request: Request) -> PipelineService:
    return request.app.state.pipeline_service
