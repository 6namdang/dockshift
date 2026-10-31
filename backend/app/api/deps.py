"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.literature import LiteratureSearchService


def get_literature_service(request: Request) -> LiteratureSearchService:
    return request.app.state.literature_service
