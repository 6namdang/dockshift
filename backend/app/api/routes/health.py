from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.environment,
        "sources": {
            "pubmed": True,
            "biorxiv": True,
            "chemrxiv": True,
            "patents": bool(settings.lens_api_token),
            "pubchem": True,
        },
    }
