from __future__ import annotations

import os

import httpx
import pytest

from app.config import Settings
from app.literature.service import LiteratureSearchService

# Never let a developer's real backend/.env leak into unit tests.
for var in ("LENS_API_TOKEN", "NCBI_API_KEY", "CONTACT_EMAIL"):
    os.environ.pop(var, None)


def make_settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        contact_email="test@example.com",
        lens_api_token="test-token",
        http_max_retries=0,
        fulltext_confidence_threshold=0.75,
        fulltext_max_docs=3,
        fulltext_max_chars=5000,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


@pytest.fixture
def service(client, settings) -> LiteratureSearchService:
    return LiteratureSearchService(client, settings)
