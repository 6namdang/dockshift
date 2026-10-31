"""FastAPI dependencies."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status

from app.literature import LiteratureSearchService
from app.qsar import QsarService
from app.structural import StructuralService


def get_literature_service(request: Request) -> LiteratureSearchService:
    return request.app.state.literature_service


def get_qsar_service(request: Request) -> QsarService:
    return request.app.state.qsar_service


def get_structural_service(request: Request) -> StructuralService:
    return request.app.state.structural_service


def authorize_structural_rest(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """Fail closed unless structural REST execution is enabled and authenticated."""
    settings = get_structural_service(request).settings
    if not settings.structural_rest_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "structural_rest_disabled",
                "message": "Structural REST execution is disabled by configuration.",
            },
        )
    configured = settings.structural_api_token
    if configured is None or not configured.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "structural_rest_misconfigured",
                "message": (
                    "Structural REST execution is enabled without STRUCTURAL_API_TOKEN; "
                    "execution is unavailable until a token is configured."
                ),
            },
        )
    scheme, separator, supplied = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not supplied:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "structural_auth_required",
                "message": "A Bearer token is required for structural REST execution.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not secrets.compare_digest(supplied, configured.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "structural_auth_invalid",
                "message": "The structural REST Bearer token is invalid.",
            },
        )
