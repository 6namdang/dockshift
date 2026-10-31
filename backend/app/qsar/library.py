"""Similarity screen over a compound library.

Finds the molecules in a library that most resemble a compound already known to work,
clusters the top of that list so the picks are not near-duplicates, and hands the picks
back for QSAR scoring.

The library is NVIDIA's nvMolKit benchmark set of 10,000 ChEMBL compounds, fetched once
(789 KB) and cached. The approach is borrowed from their science-kits-for-agents
`screen-molecules` kit; the fingerprint is the same Morgan radius 2 / 2048-bit one this
QSAR model is built on, so a hit can go straight into the model.

Cost, measured on this dataset: parsing and fingerprinting 10,000 molecules is about a
second (once, then cached in memory); ranking against a query is O(n) and effectively
free; clustering is O(n^2), so only the shortlist is ever clustered.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx
from rdkit import DataStructs
from rdkit.ML.Cluster import Butina

from app.config import BACKEND_DIR, Settings
from app.literature.http import SourceUnavailableError, request
from app.qsar.chem import fingerprint, standardise
from app.qsar.cluster import DEFAULT_CUTOFF

logger = logging.getLogger(__name__)

LIBRARY_URL = (
    "https://raw.githubusercontent.com/NVIDIA-BioNeMo/nvMolKit/main/benchmarks/data/chembl_10k.smi"
)
CACHE_DIR = BACKEND_DIR / ".cache"
LIBRARY_PATH = CACHE_DIR / "chembl_10k.smi"

DEFAULT_SHORTLIST = 200  # ranked by similarity, then clustered
MAX_SHORTLIST = 400  # the O(n^2) guard


@dataclass
class LibraryEntry:
    smiles: str
    identifier: str | None


@dataclass
class Hit:
    smiles: str
    identifier: str | None
    similarity: float


@dataclass
class Library:
    entries: list[LibraryEntry]
    fingerprints: list

    def __len__(self) -> int:
        return len(self.entries)


_library: Library | None = None
_lock = threading.Lock()


async def ensure_downloaded(client: httpx.AsyncClient, settings: Settings) -> Path:
    """Fetch the library once into the cache directory. Returns its path."""
    if LIBRARY_PATH.is_file() and LIBRARY_PATH.stat().st_size > 0:
        return LIBRARY_PATH
    logger.info("Downloading compound library (789 KB, once) from %s", LIBRARY_URL)
    response = await request(
        client,
        "GET",
        LIBRARY_URL,
        max_retries=settings.http_max_retries,
        label="compound library download",
    )
    text = response.text
    if "\n" not in text or len(text) < 1000:
        raise SourceUnavailableError("Compound library download looked empty or malformed.")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Write via a temporary file so an interrupted download cannot leave a broken cache.
    temporary = LIBRARY_PATH.with_suffix(".partial")
    temporary.write_text(text)
    temporary.replace(LIBRARY_PATH)
    return LIBRARY_PATH


def load_library() -> Library:
    """Parse and fingerprint the cached library. Cached in memory after the first call."""
    global _library
    if _library is not None:
        return _library
    with _lock:
        if _library is None:
            _library = _build()
    return _library


def _build() -> Library:
    if not LIBRARY_PATH.is_file():
        raise FileNotFoundError(
            "Compound library is not downloaded yet; call ensure_downloaded first."
        )
    entries: list[LibraryEntry] = []
    prints = []
    for line in LIBRARY_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        mol = standardise(parts[0])
        if mol is None:
            continue  # a library line that will not parse is simply skipped
        entries.append(
            LibraryEntry(smiles=parts[0], identifier=parts[1] if len(parts) > 1 else None)
        )
        prints.append(fingerprint(mol))
    logger.info("Compound library ready: %d molecules", len(entries))
    return Library(entries=entries, fingerprints=prints)


def screen(
    query_smiles: str,
    shortlist: int = DEFAULT_SHORTLIST,
    picks: int = 12,
    cutoff: float = DEFAULT_CUTOFF,
) -> tuple[list[Hit], int]:
    """Rank the library against a query, cluster the top of it, return a diverse spread.

    Returns the picks (best of each chemotype, best overall first) and how many distinct
    chemotypes the shortlist fell into.
    """
    library = load_library()
    query = standardise(query_smiles)
    if query is None:
        raise ValueError(f"Query is not a parsable structure: {query_smiles}")

    # Ranking is O(n): the whole library, every time, costs nothing.
    scores = DataStructs.BulkTanimotoSimilarity(fingerprint(query), library.fingerprints)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])

    shortlist = max(1, min(shortlist, MAX_SHORTLIST))
    top = order[:shortlist]
    top_prints = [library.fingerprints[i] for i in top]

    # Clustering needs every pairwise distance, so it runs on the shortlist only.
    distances: list[float] = []
    for position in range(len(top_prints)):
        if position:
            distances.extend(
                DataStructs.BulkTanimotoSimilarity(
                    top_prints[position], top_prints[:position], returnDistance=True
                )
            )
    clusters = Butina.ClusterData(
        distances, len(top_prints), cutoff, isDistData=True, reordering=True
    )

    # Butina orders clusters biggest-first, which has nothing to do with the query, so
    # take each cluster's best molecule and rank those by similarity.
    best_of_each = [max(members, key=lambda p: scores[top[p]]) for members in clusters]
    best_of_each.sort(key=lambda p: -scores[top[p]])

    hits = [
        Hit(
            smiles=library.entries[top[p]].smiles,
            identifier=library.entries[top[p]].identifier,
            similarity=round(scores[top[p]], 3),
        )
        for p in best_of_each[:picks]
    ]
    return hits, len(clusters)
