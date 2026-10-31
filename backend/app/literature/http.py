"""Shared HTTP helpers: one AsyncClient per process, with retry/backoff for flaky APIs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO; those URLs can carry NCBI_API_KEY, so keep it quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_SECONDS = 10.0


class SourceUnavailableError(Exception):
    """A source could not be queried (network failure, bad status, unparsable response)."""


class SourceNotConfiguredError(Exception):
    """A source needs credentials that are missing from the environment."""


def build_http_client(settings: Settings) -> httpx.AsyncClient:
    contact = f" (mailto:{settings.contact_email})" if settings.contact_email else ""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        follow_redirects=True,
        headers={"User-Agent": f"dockshift-literature/0.1{contact}"},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return min(float(header), MAX_RETRY_AFTER_SECONDS)
            except ValueError:
                pass
    return 0.5 * (2**attempt)


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int,
    label: str,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request, retrying transient failures. Raises SourceUnavailableError on failure.

    ``label`` names the upstream in error messages; never include secrets in it.
    """
    last_error = "unknown error"
    for attempt in range(max_retries + 1):
        response: httpx.Response | None = None
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code < 400:
                return response
            last_error = f"HTTP {response.status_code}: {response.text[:200].strip()}"
            if response.status_code not in RETRY_STATUSES:
                break
        if attempt < max_retries:
            delay = _retry_delay(response, attempt)
            logger.info("%s failed (%s); retrying in %.1fs", label, last_error, delay)
            await asyncio.sleep(delay)
    raise SourceUnavailableError(f"{label} request failed: {last_error}")
