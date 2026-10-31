"""Resolve compound names to structures via PubChem (no API key needed)."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

import httpx

from app.config import Settings
from app.literature.http import SourceUnavailableError, request  # shared retrying HTTP helper

PUBCHEM_NAME_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name"

# PubChem asks for no more than 5 requests/second from one client. A batch of 50
# compounds would otherwise fire 50 lookups at once and earn a 429 for all of them.
_MAX_CONCURRENT = 3
_gate = asyncio.Semaphore(_MAX_CONCURRENT)

# Resolved names are stable, so remember them for the life of the process. Bounded so a
# long-running server cannot grow it without limit.
_CACHE_LIMIT = 2048
_cache: dict[str, tuple[str, int] | None] = {}


async def resolve_name(
    client: httpx.AsyncClient, settings: Settings, name: str
) -> tuple[str, int] | None:
    """Return (smiles, cid) for a compound name, or None if PubChem has no such name.

    Raises SourceUnavailableError if PubChem itself is unreachable or rate-limiting, so a
    lookup failure stays distinguishable from an unknown compound.
    """
    key = name.strip().lower()
    if key in _cache:
        return _cache[key]

    url = (
        f"{PUBCHEM_NAME_URL}/{quote(name.strip(), safe='')}/property/SMILES,ConnectivitySMILES/JSON"
    )
    try:
        async with _gate:
            response = await request(
                client,
                "GET",
                url,
                max_retries=max(1, settings.http_max_retries),
                label="PubChem name lookup",
            )
    except SourceUnavailableError as exc:
        message = str(exc)
        if "HTTP 404" in message:
            _remember(key, None)  # PubChem answers 404 for names it does not know
            return None
        if "HTTP 429" in message:
            # Don't surface PubChem's HTML error page to the caller.
            raise SourceUnavailableError(
                "PubChem is rate-limiting this client. Wait a moment and try again."
            ) from exc
        raise

    try:
        records = response.json()["PropertyTable"]["Properties"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceUnavailableError(f"PubChem returned an unexpected response: {exc}") from exc

    result: tuple[str, int] | None = None
    if records:
        record = records[0]
        # Prefer the stereochemistry-bearing SMILES; fall back to the flat connectivity one.
        smiles = record.get("SMILES") or record.get("ConnectivitySMILES")
        cid = record.get("CID")
        if smiles and cid is not None:
            result = (str(smiles), int(cid))
    _remember(key, result)
    return result


def _remember(key: str, value: tuple[str, int] | None) -> None:
    if len(_cache) >= _CACHE_LIMIT:
        _cache.clear()
    _cache[key] = value
