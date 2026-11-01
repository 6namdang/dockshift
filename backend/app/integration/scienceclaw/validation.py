"""Scientific guards reused from the source system."""

import math
from dataclasses import dataclass

from .contracts import ContractViolation

MEASURED_ENDPOINTS = frozenset({"IC50", "EC50", "Ki", "Kd"})


PREDICTED_ENDPOINTS = frozenset(
    {"vina_score", "docking_energy", "mmgbsa", "qsar_prediction", "model_confidence"}
)


_MOLAR_PER_UNIT = {"M": 1.0, "mM": 1e-3, "uM": 1e-6, "µM": 1e-6, "nM": 1e-9, "pM": 1e-12}


def p_activity(value: float, unit: str, endpoint: str) -> float:
    """Eq. 3: pIC50 = -log10(IC50 / 1 M), for a *measured* endpoint only.

    Raises if handed a predicted quantity. This guard is the executable form of
    "a predicted docking energy is never transformed into pIC50 or pKd".
    """
    if endpoint in PREDICTED_ENDPOINTS:
        raise ContractViolation(
            f"{endpoint} is a computational prediction; converting it to a p-scale "
            "would present a scoring-function output as a measured affinity"
        )
    if endpoint not in MEASURED_ENDPOINTS:
        raise ContractViolation(f"unknown endpoint {endpoint!r}; declare it before conversion")
    if unit not in _MOLAR_PER_UNIT:
        raise ContractViolation(f"unit {unit!r} is not a supported molar unit")
    if value <= 0:
        raise ContractViolation("activity value must be positive to take a logarithm")
    return -math.log10(value * _MOLAR_PER_UNIT[unit])


@dataclass
class TargetIdentity:
    """A frozen claim about what protein we are working on."""

    label: str
    species: str
    accession: str | None
    accession_source: str | None
    sequence_sha256: str | None
    structure_id: str | None
    structure_kind: str | None  # experimental | predicted
    isoform: str | None = None
    verified: bool = False

    def check(self) -> list[str]:
        """Return blocking reasons. An unverified accession is a blocker."""
        problems = []
        if not self.accession:
            problems.append(f"{self.label}: no accession supplied")
        if not self.accession_source:
            problems.append(f"{self.label}: accession has no named source")
        if not self.verified:
            problems.append(
                f"{self.label}: accession not marked verified -- identifiers must come "
                "from a checked source, not from a generated guess"
            )
        if self.structure_id and self.structure_kind not in ("experimental", "predicted"):
            problems.append(f"{self.label}: structure_kind must be 'experimental' or 'predicted'")
        return problems


FORBIDDEN_COMBINATIONS = (
    ("vina_best_score", "complex_confidence"),
    ("vina_best_score", "interface_confidence"),
)


def forbid_score_mixing(metric_names: list[str]) -> None:
    """Refuse any attempt to pool metrics from incompatible physical questions."""
    present = set(metric_names)
    for a, b in FORBIDDEN_COMBINATIONS:
        if a in present and b in present:
            raise ContractViolation(
                f"{a} and {b} describe different physical questions in different units; "
                "they are reported side by side, never summed or averaged"
            )
