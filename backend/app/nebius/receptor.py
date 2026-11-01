"""The hTERT receptor and the three sites candidates are docked against.

Receptor is PDB 9Q14: the human telomerase catalytic core with TPP1, a DNA primer and
BIBR1532 (ligand code 55C) bound, 3.0 A cryo-EM. Fetched once from RCSB and cached.

Three sites, all on the same receptor so species and structure are held constant:

  A  the real human site, taken from where BIBR1532 actually sits in 9Q14
  B  the human equivalent of the tcTERT FVYL thumb pocket (F1012, V1025, Y1089, L1092),
     which is what the pre-2026 literature designed against
  C  a decoy pocket far from both, as a null control

DiffDock takes no box: it searches whatever receptor it is given. Targeting a site
therefore means handing it a receptor trimmed around that site.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from app.config import BACKEND_DIR, Settings
from app.literature.http import SourceUnavailableError, request

logger = logging.getLogger(__name__)

PDB_ID = "9Q14"
RCSB_URL = f"https://files.rcsb.org/download/{PDB_ID}.pdb"
CACHE_DIR = BACKEND_DIR / ".cache"
RECEPTOR_PATH = CACHE_DIR / f"{PDB_ID.lower()}.pdb"

LIGAND_CODE = "55C"  # BIBR1532, as deposited
# The human equivalents of the beetle FVYL motif.
FVYL_RESIDUES = {("PHE", 1012), ("VAL", 1025), ("TYR", 1089), ("LEU", 1092)}
DEFAULT_RADIUS = 18.0  # angstrom of protein kept around a site centroid


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    description: str
    centroid: tuple[float, float, float]


_structure: list[str] | None = None
_lock = threading.Lock()


async def ensure_receptor(client: httpx.AsyncClient, settings: Settings) -> Path:
    """Download 9Q14 once into the cache."""
    if RECEPTOR_PATH.is_file() and RECEPTOR_PATH.stat().st_size > 100_000:
        return RECEPTOR_PATH
    logger.info("Downloading %s from RCSB", PDB_ID)
    response = await request(
        client, "GET", RCSB_URL, max_retries=settings.http_max_retries, label=f"RCSB {PDB_ID}"
    )
    text = response.text
    if "ATOM" not in text:
        raise SourceUnavailableError(f"{PDB_ID} download contained no ATOM records.")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = RECEPTOR_PATH.with_suffix(".partial")
    temporary.write_text(text)
    temporary.replace(RECEPTOR_PATH)
    return RECEPTOR_PATH


def _lines() -> list[str]:
    global _structure
    if _structure is not None:
        return _structure
    with _lock:
        if _structure is None:
            if not RECEPTOR_PATH.is_file():
                raise FileNotFoundError("9Q14 is not downloaded yet; call ensure_receptor first.")
            _structure = RECEPTOR_PATH.read_text().splitlines()
    return _structure


def _xyz(line: str) -> tuple[float, float, float]:
    return float(line[30:38]), float(line[38:46]), float(line[46:54])


def _protein_atoms() -> list[str]:
    return [ln for ln in _lines() if ln.startswith("ATOM")]


def deposited_ligand() -> list[str]:
    """The BIBR1532 HETATM records, used as the redocking reference."""
    return [ln for ln in _lines() if ln.startswith("HETATM") and ln[17:20].strip() == LIGAND_CODE]


def sites() -> list[Site]:
    """The three docking sites, computed from the structure itself."""
    ligand = np.array([_xyz(ln) for ln in deposited_ligand()])
    site_a = ligand.mean(axis=0)

    fvyl = [
        _xyz(ln)
        for ln in _protein_atoms()
        if ln[21] == "A" and (ln[17:20].strip(), int(ln[22:26])) in FVYL_RESIDUES
    ]
    site_b = np.array(fvyl).mean(axis=0)

    chain_a = np.array([_xyz(ln) for ln in _protein_atoms() if ln[21] == "A"])
    site_c = chain_a[np.argmax(np.linalg.norm(chain_a - site_a, axis=1))]

    return [
        Site(
            id="site_a_human",
            name="Human BIBR1532 site",
            description=(
                "Where BIBR1532 actually sits in 9Q14: the reverse-transcriptase domain "
                "between fingers and palm, against the RNA template."
            ),
            centroid=tuple(round(float(v), 2) for v in site_a),
        ),
        Site(
            id="site_b_fvyl",
            name="FVYL pocket (human equivalent)",
            description=(
                "F1012, V1025, Y1089, L1092 - the human counterpart of the tcTERT thumb "
                "pocket the pre-2026 literature designed against. 49 A from the real site."
            ),
            centroid=tuple(round(float(v), 2) for v in site_b),
        ),
        Site(
            id="site_c_decoy",
            name="Decoy pocket",
            description="A surface site far from both, as a null control.",
            centroid=tuple(round(float(v), 2) for v in site_c),
        ),
    ]


def receptor_for(centroid: tuple[float, float, float], radius: float = DEFAULT_RADIUS) -> str:
    """Whole residues with any atom within ``radius`` of the centroid, as PDB text.

    Whole residues are kept, never part of one, so the fragment stays chemically sane.
    """
    atoms = _protein_atoms()
    coordinates = np.array([_xyz(ln) for ln in atoms])
    distance = np.linalg.norm(coordinates - np.asarray(centroid), axis=1)
    keep = {(ln[21], ln[22:27]) for ln, d in zip(atoms, distance, strict=True) if d <= radius}
    rows = [ln for ln in atoms if (ln[21], ln[22:27]) in keep]
    return "\n".join(rows) + "\nEND\n"


def full_receptor() -> str:
    """The whole protein, ligand stripped."""
    return "\n".join(_protein_atoms()) + "\nEND\n"
