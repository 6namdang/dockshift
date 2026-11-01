"""RDKit port: canonicalisation, validity and structural metadata (spec 5.2-5.3).

`Vchem(x)` from eq. 7 lives here. The checks are deliberately structural --
valence, parse, required scaffold, permitted attachment, duplicate, stereo
change -- and none of them is a drug-likeness verdict. Descriptors are recorded
as context, not as a pass/fail gate on a candidate's worth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import Adapter, ToolFailed, ToolProbe, probe_python_module


@dataclass
class ChemAudit:
    """Outcome of Vchem for one structure. `valid` is 1/0 in eq. 7 terms."""

    input_repr: str
    valid: bool
    canonical_smiles: str | None = None
    inchikey: str | None = None
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    descriptors: dict[str, float] = field(default_factory=dict)


class RDKitAdapter(Adapter):
    name = "rdkit"
    error_code = "RDKIT_NOT_INSTALLED"

    def probe(self) -> ToolProbe:
        probe = probe_python_module("rdkit", self.name, self.error_code)
        if probe.available:
            try:
                from rdkit import rdBase

                return ToolProbe(self.name, True, rdBase.rdkitVersion)
            except Exception as exc:  # pragma: no cover
                return ToolProbe(self.name, False, None, self.error_code, str(exc))
        return probe

    # -- Vchem -------------------------------------------------------------

    def audit(
        self,
        smiles: str,
        required_substructure_smarts: str | None = None,
        forbidden_substructure_smarts: list[str] | None = None,
        parent_inchikey: str | None = None,
    ) -> ChemAudit:
        """Run the frozen structural checks on one candidate structure."""
        self.require()
        from rdkit import Chem, RDLogger
        from rdkit.Chem import Crippen, Descriptors, inchi

        RDLogger.DisableLog("rdApp.*")
        audit = ChemAudit(input_repr=smiles, valid=False)

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            audit.failures.append("PARSE_FAILED")
            return audit

        try:
            Chem.SanitizeMol(mol)
        except Exception as exc:
            audit.failures.append(f"SANITIZE_FAILED:{type(exc).__name__}")
            return audit

        problems = Chem.DetectChemistryProblems(mol)
        for problem in problems:
            audit.failures.append(f"CHEMISTRY_PROBLEM:{problem.GetType()}")

        if required_substructure_smarts:
            patt = Chem.MolFromSmarts(required_substructure_smarts)
            if patt is None:
                raise ToolFailed("BAD_CONSTRAINT", "required substructure SMARTS did not parse")
            if not mol.HasSubstructMatch(patt):
                audit.failures.append("REQUIRED_SCAFFOLD_LOST")

        for smarts in forbidden_substructure_smarts or []:
            patt = Chem.MolFromSmarts(smarts)
            if patt is None:
                raise ToolFailed("BAD_CONSTRAINT", f"forbidden SMARTS did not parse: {smarts}")
            if mol.HasSubstructMatch(patt):
                audit.failures.append(f"FORBIDDEN_SUBSTRUCTURE:{smarts}")

        audit.canonical_smiles = Chem.MolToSmiles(mol)
        try:
            audit.inchikey = inchi.MolToInchiKey(mol)
        except Exception:
            audit.warnings.append("INCHIKEY_UNAVAILABLE")

        if parent_inchikey and audit.inchikey == parent_inchikey:
            audit.failures.append("DUPLICATE_OF_PARENT")

        unspecified = [
            str(c.GetIdx())
            for c in mol.GetAtoms()
            if c.GetChiralTag() == Chem.ChiralType.CHI_UNSPECIFIED
            and c.HasProp("_ChiralityPossible")
        ]
        if unspecified:
            audit.warnings.append(f"UNSPECIFIED_STEREOCENTRES:{','.join(unspecified)}")

        if mol.GetNumAtoms() and all(a.GetFormalCharge() == 0 for a in mol.GetAtoms()):
            audit.warnings.append("PROTONATION_ASSUMED_NEUTRAL_AT_PH_UNSPECIFIED")

        audit.descriptors = {
            "molecular_weight_da": float(Descriptors.MolWt(mol)),
            "tpsa_a2": float(Descriptors.TPSA(mol)),
            "clogp_crippen": float(Crippen.MolLogP(mol)),
            "hbond_donors": float(Descriptors.NumHDonors(mol)),
            "hbond_acceptors": float(Descriptors.NumHAcceptors(mol)),
            "rotatable_bonds": float(Descriptors.NumRotatableBonds(mol)),
            "formal_charge": float(Chem.GetFormalCharge(mol)),
        }
        audit.valid = not audit.failures
        return audit

    def deduplicate(self, audits: list[ChemAudit]) -> list[ChemAudit]:
        """Keep the first occurrence of each distinct chemical entity."""
        seen: set[str] = set()
        unique: list[ChemAudit] = []
        for audit in audits:
            key = audit.inchikey or audit.canonical_smiles or audit.input_repr
            if key in seen:
                audit.failures.append("DUPLICATE_IN_BATCH")
                audit.valid = False
                continue
            seen.add(key)
            unique.append(audit)
        return unique
