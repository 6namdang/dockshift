"""Compare molecules with each other: pairwise similarity and chemotype clustering.

Ranking alone cannot tell you whether a shortlist is six distinct chemotypes or one
molecule wearing six hats. Butina clustering over Tanimoto distance answers that.

The approach is borrowed from NVIDIA's science-kits-for-agents `screen-molecules` kit,
which uses the same Morgan radius 2 / 2048-bit fingerprint this QSAR model is built on.
Clustering needs every pairwise distance, so it is O(n^2): fine for a shortlist of a few
hundred, and deliberately never run over a whole library.
"""

from __future__ import annotations

from rdkit import DataStructs
from rdkit.ML.Cluster import Butina

from app.qsar.chem import fingerprint, standardise

# Distance cutoff: molecules closer than this land in the same chemotype. 0.6 Tanimoto
# distance (0.4 similarity) is the value the upstream kit uses.
DEFAULT_CUTOFF = 0.6
# Guard the O(n^2) half. A shortlist is tens of molecules; this is a long way above that.
MAX_MOLECULES = 500


def _fingerprints(smiles: list[str]) -> list:
    out = []
    for s in smiles:
        mol = standardise(s) if s else None
        out.append(fingerprint(mol) if mol is not None else None)
    return out


def similarity_matrix(smiles: list[str]) -> list[list[float | None]]:
    """Full pairwise Tanimoto similarity. None where a structure could not be parsed."""
    fps = _fingerprints(smiles[:MAX_MOLECULES])
    size = len(fps)
    matrix: list[list[float | None]] = [[None] * size for _ in range(size)]
    for i, fp_i in enumerate(fps):
        if fp_i is None:
            continue
        matrix[i][i] = 1.0
        for j in range(i + 1, size):
            fp_j = fps[j]
            if fp_j is None:
                continue
            value = round(DataStructs.TanimotoSimilarity(fp_i, fp_j), 3)
            matrix[i][j] = matrix[j][i] = value
    return matrix


def cluster(smiles: list[str], cutoff: float = DEFAULT_CUTOFF) -> list[int | None]:
    """Group molecules into chemotypes. Returns a cluster id per molecule, None if unparsed.

    Cluster ids are assigned so that 0 is the largest group, matching Butina's own
    ordering, and are stable for a given input order.
    """
    fps = _fingerprints(smiles[:MAX_MOLECULES])
    usable = [i for i, fp in enumerate(fps) if fp is not None]
    assignment: list[int | None] = [None] * len(fps)
    if not usable:
        return assignment

    # Butina wants the condensed lower triangle, in order.
    distances: list[float] = []
    for pos, i in enumerate(usable):
        if pos:
            distances.extend(
                DataStructs.BulkTanimotoSimilarity(
                    fps[i], [fps[j] for j in usable[:pos]], returnDistance=True
                )
            )
    groups = Butina.ClusterData(distances, len(usable), cutoff, isDistData=True, reordering=True)
    for cluster_id, members in enumerate(groups):
        for member in members:
            assignment[usable[member]] = cluster_id
    return assignment


def pick_diverse(order: list[int], clusters: list[int | None], count: int) -> list[int]:
    """Choose ``count`` indices from ``order``, best first, one per chemotype before repeating.

    ``order`` is the indices already sorted best-first. The result keeps that preference
    but takes the best member of each cluster first, so a shortlist is not six variations
    on one scaffold. Molecules with no cluster are treated as their own chemotype.
    """
    seen: set[int] = set()
    first_pass: list[int] = []
    rest: list[int] = []
    for idx in order:
        key = clusters[idx] if idx < len(clusters) and clusters[idx] is not None else -idx - 1
        if key in seen:
            rest.append(idx)
        else:
            seen.add(key)
            first_pass.append(idx)
    return (first_pass + rest)[:count]
