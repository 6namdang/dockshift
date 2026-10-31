"""RDKit chemistry: standardisation, featurisation and drug-likeness properties.

Featurisation mirrors the upstream repo exactly: a 2048-bit Morgan fingerprint
(radius 2) concatenated with the 195 named RDKit 2D descriptors the model was fitted
on. Descriptors are selected *by name*, so a local RDKit holding a different total set
still produces the same vector as long as those names exist.
"""

from __future__ import annotations

import numpy as np
from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import QED, Descriptors, rdMolDescriptors
from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator
from rdkit.Chem.SaltRemover import SaltRemover

RDLogger.DisableLog("rdApp.*")  # RDKit writes parse failures straight to stderr

FP_BITS = 2048
FP_RADIUS = 2

_generator = GetMorganGenerator(radius=FP_RADIUS, fpSize=FP_BITS)
_salt_remover = SaltRemover()
# name -> function, so we compute only the descriptors the model needs.
_DESCRIPTOR_FUNCS = dict(Descriptors.descList)


def standardise(smiles: str) -> Chem.Mol | None:
    """Parse and standardise a SMILES string: strip salts, keep the largest fragment.

    Returns None if the string is not a parsable structure.
    """
    if not smiles or not smiles.strip():
        return None
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        return None
    mol = _salt_remover.StripMol(mol, dontRemoveEverything=True)
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    fragments = Chem.GetMolFrags(mol, asMols=True)
    if len(fragments) > 1:
        mol = max(fragments, key=lambda m: m.GetNumHeavyAtoms())
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    return mol


def canonical_smiles(mol: Chem.Mol) -> str:
    return Chem.MolToSmiles(mol, canonical=True)


def fingerprint(mol: Chem.Mol):
    """Bit vector, for Tanimoto comparisons."""
    return _generator.GetFingerprint(mol)


def bulk_tanimoto(mol: Chem.Mol, others: list) -> list[float]:
    if not others:
        return []
    return DataStructs.BulkTanimotoSimilarity(fingerprint(mol), others)


def featurise(mol: Chem.Mol, descriptor_names: list[str]) -> np.ndarray:
    """Build the model's 2243-dimensional input row for one molecule."""
    fp = _generator.GetFingerprintAsNumPy(mol).astype(float)
    values = np.empty(len(descriptor_names), dtype=float)
    for i, name in enumerate(descriptor_names):
        func = _DESCRIPTOR_FUNCS.get(name)
        if func is None:
            values[i] = np.nan  # absent in this RDKit build; XGBoost handles NaN
            continue
        try:
            values[i] = func(mol)
        except Exception:
            values[i] = np.nan
    return np.concatenate([fp, values]).reshape(1, -1)


def properties(mol: Chem.Mol) -> dict[str, float | int | bool]:
    """Physicochemical and drug-likeness properties (upstream script 06)."""
    mw = Descriptors.MolWt(mol)
    clogp = Descriptors.MolLogP(mol)
    hbd = rdMolDescriptors.CalcNumHBD(mol)
    hba = rdMolDescriptors.CalcNumHBA(mol)
    tpsa = Descriptors.TPSA(mol)
    rotatable = rdMolDescriptors.CalcNumRotatableBonds(mol)
    violations = int(sum([mw > 500, clogp > 5, hbd > 5, hba > 10]))
    return {
        "molecular_weight": round(mw, 2),
        "clogp": round(clogp, 2),
        "hbd": int(hbd),
        "hba": int(hba),
        "tpsa": round(tpsa, 1),
        "rotatable_bonds": int(rotatable),
        "aromatic_rings": int(rdMolDescriptors.CalcNumAromaticRings(mol)),
        "qed": round(QED.qed(mol), 3),
        "lipinski_violations": violations,
        "lipinski_pass": violations <= 1,
        "veber_pass": bool(rotatable <= 10 and tpsa <= 140),
    }


def looks_like_smiles(text: str) -> bool:
    """Guess whether a string is a structure rather than a compound name.

    Names are resolved through PubChem, so this only has to avoid sending obvious
    structures over the network; anything ambiguous is parsed first and looked up only
    if parsing fails.
    """
    candidate = text.strip()
    if not candidate or " " in candidate:
        return False
    return Chem.MolFromSmiles(candidate) is not None
