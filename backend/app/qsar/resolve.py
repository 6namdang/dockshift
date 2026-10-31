"""Resolve compound names to structures via PubChem (no API key needed)."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.config import Settings
from app.literature.http import SourceUnavailableError, request  # shared retrying HTTP helper

PUBCHEM_NAME_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name"


async def resolve_name(
    client: httpx.AsyncClient, settings: Settings, name: str
) -> tuple[str, int] | None:
    """Return (smiles, cid) for a compound name, or None if PubChem has no such name.

    Raises SourceUnavailableError if PubChem itself is unreachable, so a lookup failure
    is distinguishable from an unknown compound.
    """
    url = (
        f"{PUBCHEM_NAME_URL}/{quote(name.strip(), safe='')}/property/SMILES,ConnectivitySMILES/JSON"
    )
    try:
        response = await request(
            client,
            "GET",
            url,
            max_retries=min(1, settings.http_max_retries),
            label="PubChem name lookup",
        )
    except SourceUnavailableError as exc:
        if "HTTP 404" in str(exc):
            return None  # PubChem answers 404 for names it does not know
        raise
    try:
        records = response.json()["PropertyTable"]["Properties"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceUnavailableError(f"PubChem returned an unexpected response: {exc}") from exc
    if not records:
        return None
    record = records[0]
    # Prefer the stereochemistry-bearing SMILES; fall back to the flat connectivity one.
    smiles = record.get("SMILES") or record.get("ConnectivitySMILES")
    cid = record.get("CID")
    if not smiles or cid is None:
        return None
    return str(smiles), int(cid)
