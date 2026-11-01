"""Model-specific scientific output checks, independent of LLM assertions.

Only hash-verified bytes are inputs. Supported layouts are explicit; unknown
native layouts block. Passing format/identity checks is not experimental validation.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from rdkit import Chem

from .remote import objects
from .scienceclaw.adapters.base import ToolFailed, ToolUnavailable

FOLD_TOOLS = {
    "infer_openfold2_native": "openfold2",
    "infer_openfold3_native": "openfold3",
    "submit_alphafold3": "alphafold3",
    "submit_esmfold2": "esmfold2",
    "submit_protenix_v2": "protenix-v2",
    "boltz2_predict_native": "boltz2",
}
DESIGN_TOOLS = {
    "infer_proteinmpnn_native": "proteinmpnn",
    "submit_rfdiffusion": "rfdiffusion",
    "submit_rfd4_proteina": "rfd4-proteina",
    "submit_proteina_complexa": "proteina-complexa",
    "submit_boltzgen": "boltzgen",
}
MOLECULE_TOOLS = {"genmol_generate": "genmol", "molmim_run_native": "molmim"}
AA = dict(
    zip(
        ("ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL").split(),
        "ARNDCQEGHILKMFPSTWYV",
        strict=True,
    )
)
LIMITATIONS = [
    "Format, chemistry and model-confidence checks do not establish binding or efficacy.",
    "Model-native scores remain separate; no potency conversion or cross-model pooling.",
    "Predicted constructs and missing biological context require scientist review.",
]


def finite(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ToolFailed("NONFINITE_SCIENTIFIC_OUTPUT", f"{name} is not a finite number.")
    if (low is not None and value < low) or (high is not None and value > high):
        raise ToolFailed("SCIENTIFIC_RANGE_ERROR", f"{name} is outside its native range.")
    return value


def sequence(value):
    if not isinstance(value, str) or not value or any(c not in AA.values() for c in value):
        raise ToolFailed("INVALID_PROTEIN_SEQUENCE", "Canonical protein sequence required.")
    return value


def read_structure(text, fmt="pdb"):
    """Read all atoms, not an RDKit proximity-bond guess. Never align coordinates."""
    residues, atoms = {}, []
    if fmt in ("cif", "mmcif"):
        try:
            import gemmi
        except ImportError as exc:
            raise ToolUnavailable(
                "CIF_PARSER_REQUIRED", "Install the optional gemmi parser."
            ) from exc
        try:
            structure = gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
            if len(structure) != 1:
                raise ValueError("Exactly one structure model required")
            for chain in structure[0]:
                for residue in chain:
                    for atom in residue:
                        if atom.altloc not in ("\x00", " ", "A"):
                            raise ValueError("Unreviewed alternate conformer")
                        key = (chain.name, str(residue.seqid))
                        residues[key] = residue.name
                        atoms.append(
                            (
                                chain.name,
                                str(residue.seqid),
                                atom.name,
                                atom.pos.x,
                                atom.pos.y,
                                atom.pos.z,
                            )
                        )
        except Exception as exc:
            raise ToolFailed(
                "INVALID_STRUCTURE", "Cannot parse an unambiguous mmCIF model."
            ) from exc
    else:
        if sum(line.startswith("MODEL ") for line in text.splitlines()) > 1:
            raise ToolFailed(
                "AMBIGUOUS_STRUCTURE", "Multiple coordinate models need explicit selection."
            )
        for line in text.splitlines():
            if not line.startswith(("ATOM  ", "HETATM")):
                continue
            try:
                if line[16] not in (" ", "A"):
                    raise ValueError("Unreviewed alternate conformer")
                chain, res, name = line[21].strip() or "_", line[22:27].strip(), line[12:16].strip()
                key = (chain, res)
                if key in residues and residues[key] != line[17:20].strip():
                    raise ValueError("Residue name conflict")
                residues[key] = line[17:20].strip()
                atoms.append(
                    (chain, res, name, float(line[30:38]), float(line[38:46]), float(line[46:54]))
                )
            except (ValueError, IndexError) as exc:
                raise ToolFailed("INVALID_STRUCTURE", "Malformed PDB atom record.") from exc
    if not atoms or not np.isfinite(np.asarray([a[3:] for a in atoms], dtype=float)).all():
        raise ToolFailed("INVALID_STRUCTURE", "Empty/non-finite coordinates.")
    keys = [a[:3] for a in atoms]
    if len(keys) != len(set(keys)):
        raise ToolFailed("DUPLICATE_ATOMS", "Duplicate coordinate atom identity.")
    chains = {}
    for (chain, _), name in residues.items():
        if name in AA:
            chains[chain] = chains.get(chain, "") + AA[name]
    if not chains:
        raise ToolFailed("PROTEIN_COORDINATES_REQUIRED", "No canonical protein residues found.")
    # Extreme overlaps are a format/geometry failure, not a complete clash/energy audit.
    xyz = np.asarray([a[3:] for a in atoms], dtype=float)
    for start in range(0, len(xyz), 128):
        d = np.linalg.norm(xyz[start : start + 128, None] - xyz[None, :], axis=-1)
        for i in range(len(d)):
            d[i, start + i] = np.inf
        if (d < 0.1).any():
            raise ToolFailed("COINCIDENT_ATOMS", "Distinct atoms overlap within 0.1 angstrom.")
    return {"chains": chains, "atom_count": len(atoms), "residue_count": len(residues)}, xyz, atoms


def confidence_fields(document, require_interface=False, residue_count=None):
    """Preserve native ranges: pLDDT 0..100, ipTM/pTM 0..1, PAE angstrom."""
    found = {}
    for node in objects(document):
        for name, low, high in (
            ("plddt", 0, 100),
            ("pLDDT", 0, 100),
            ("ptm", 0, 1),
            ("iptm", 0, 1),
            ("pTM", 0, 1),
            ("ipTM", 0, 1),
            ("pae", 0, None),
        ):
            if name not in node:
                continue
            value = node[name]
            if isinstance(value, list):
                shape = np.asarray(value).shape
                if name == "pae" and (
                    len(shape) != 2
                    or shape[0] != shape[1]
                    or residue_count is not None
                    and shape[0] != residue_count
                ):
                    raise ToolFailed(
                        "INVALID_PAE_SHAPE", "PAE must be a square, residue-matched matrix."
                    )
                if name in ("plddt", "pLDDT") and (
                    len(shape) != 1 or residue_count is not None and shape[0] != residue_count
                ):
                    raise ToolFailed(
                        "INVALID_PLDDT_SHAPE", "Per-residue confidence must match residue count."
                    )
            flat = np.asarray(value).reshape(-1).tolist() if isinstance(value, list) else [value]
            if not flat:
                raise ToolFailed("EMPTY_CONFIDENCE", "Confidence values are empty.")
            for number in flat:
                finite(number, name, low, high)
            # Multiple samples retain separate observations rather than overwriting values.
            found.setdefault(name, []).append(value)
    if not found or (require_interface and not any(k in found for k in ("iptm", "ipTM"))):
        raise ToolUnavailable(
            "NATIVE_CONFIDENCE_REQUIRED", "Native confidence metrics are missing."
        )
    return found


def documents(result):
    artifacts = result.get("artifacts", [])
    if not artifacts or not all(a.get("hash_verified") for a in artifacts):
        raise ToolUnavailable("VERIFIED_ARTIFACT_REQUIRED", "No hash-verified model artifacts.")
    docs = [a["data"] for a in artifacts if isinstance(a.get("data"), dict)]
    if not docs:
        raise ToolUnavailable("MODEL_METADATA_REQUIRED", "Native result metadata is missing.")
    return docs


def model_version(docs, model):
    candidates = [
        n for d in docs for n in objects(d) if n.get("model_version") or n.get("engine_version")
    ]
    for n in candidates:
        if n.get("model_id") != model:
            continue
        return n.get("model_version") or n["engine_version"]
    raise ToolUnavailable("MODEL_VERSION_REQUIRED", "Native model version is absent or mismatched.")


def structures(result, docs, out):
    records = []
    for artifact in result["artifacts"]:
        filename = artifact["filename"]
        if filename.endswith((".pdb", ".cif", ".mmcif")):
            records.append(
                {
                    "format": Path(filename).suffix.lstrip("."),
                    "text": (out / filename).read_text(),
                    "filename": filename,
                }
            )
    for d in docs:
        for node in objects(d):
            # Explicit inline native structure fields. Arbitrary strings/URLs are not structures.
            for key, fmt in (
                ("pdb", "pdb"),
                ("pdb_string", "pdb"),
                ("cif", "cif"),
                ("mmcif", "cif"),
            ):
                if isinstance(node.get(key), str):
                    records.append({"format": fmt, "text": node[key]})
    if not records:
        raise ToolUnavailable(
            "MODEL_STRUCTURE_REQUIRED", "No supported coordinate artifact layout."
        )
    unique = {r["text"]: r for r in records}
    return list(unique.values())


def validate_output(tool, result, acceptance, out):
    docs = documents(result)
    model = {**FOLD_TOOLS, **DESIGN_TOOLS, **MOLECULE_TOOLS}.get(tool)
    if model is None:
        raise ToolUnavailable("MODEL_VALIDATOR_REQUIRED", "No model-specific output validator.")
    version = model_version(docs, model)
    import sys
    from importlib.metadata import version as package_version

    data = {
        "model_id": model,
        "model_version": version,
        "limitations": list(LIMITATIONS),
        "validation_versions": {
            "python": sys.version.split()[0],
            "rdkit": package_version("rdkit"),
            "numpy": np.__version__,
        },
    }
    if tool in MOLECULE_TOOLS:
        rows = [
            n["molecules"] for d in docs for n in objects(d) if isinstance(n.get("molecules"), list)
        ]
        if not rows or not rows[0]:
            raise ToolUnavailable(
                "GENERATED_MOLECULES_REQUIRED", "No native generated molecule list."
            )
        mols, seen = [], set()
        for row in rows[0]:
            smi = row if isinstance(row, str) else row.get("smiles")
            mol = Chem.MolFromSmiles(smi or "")
            if mol is None or mol.GetNumHeavyAtoms() == 0 or len(Chem.GetMolFrags(mol)) != 1:
                raise ToolFailed(
                    "INVALID_GENERATED_CHEMISTRY", "Generated molecule failed RDKit checks."
                )
            canonical = Chem.MolToSmiles(mol, isomericSmiles=True)
            if canonical in seen:
                continue
            seen.add(canonical)
            if mol.GetNumHeavyAtoms() > acceptance.get("max_heavy_atoms", 80):
                raise ToolFailed("MOLECULE_SIZE_LIMIT", "Generated molecule exceeds reviewed size.")
            scores = (
                {}
                if isinstance(row, str)
                else {
                    k: finite(v, k)
                    for k, v in row.items()
                    if k in ("score", "qed", "logp", "QED", "LogP")
                }
            )
            mols.append(
                {
                    "smiles": canonical,
                    "heavy_atoms": mol.GetNumHeavyAtoms(),
                    "formal_charge": Chem.GetFormalCharge(mol),
                    "native_scores": scores,
                }
            )
        if len(mols) != acceptance.get("requested_molecules", len(mols)):
            raise ToolUnavailable(
                "GENERATION_COUNT_INCOMPLETE",
                "The requested number of distinct valid molecules was not produced.",
            )
        data["molecules"] = mols
        data["kind"] = "molecules"
        data["limitations"].append(
            "QED/LogP are descriptors, not target activity. SAFE masks do not bound heavy atoms."
        )
        return data
    if tool == "infer_proteinmpnn_native":
        rows = [
            n["sequences"] for d in docs for n in objects(d) if isinstance(n.get("sequences"), list)
        ]
        if not rows or not rows[0]:
            raise ToolUnavailable(
                "DESIGNED_SEQUENCES_REQUIRED", "No native designed sequence list."
            )
        expected_length = acceptance.get("binder_length")
        if not isinstance(expected_length, int) or expected_length <= 0:
            raise ToolUnavailable(
                "BINDER_LENGTH_REQUIRED", "Review exact design-chain length first."
            )
        seqs = []
        for row in rows[0]:
            if not isinstance(row, dict):
                raise ToolUnavailable(
                    "SEQUENCE_SCORE_REQUIRED", "Native sequence and compatibility score required."
                )
            seq = sequence(row.get("sequence"))
            if len(seq) != expected_length:
                raise ToolFailed(
                    "SEQUENCE_LENGTH_MISMATCH", "Design differs from reviewed backbone length."
                )
            seqs.append({"sequence": seq, "score": finite(row.get("score"), "ProteinMPNN score")})
        if len(seqs) != acceptance.get("requested_designs", len(seqs)):
            raise ToolUnavailable(
                "DESIGN_COUNT_INCOMPLETE", "Native design count differs from the requested budget."
            )
        data.update(kind="sequences", sequences=seqs)
        data["limitations"].append(
            "ProteinMPNN compatibility score is not affinity or backbone gener"
            "ation; nuclear delivery is unresolved."
        )
        return data
    records = structures(result, docs, out)
    expected = acceptance.get("chains")
    if tool in FOLD_TOOLS and not expected:
        raise ToolUnavailable(
            "EXPECTED_CHAINS_REQUIRED", "Exact reviewed chain sequences are required."
        )
    checked = []
    for index, record in enumerate(records):
        info, xyz, atom_rows = read_structure(record["text"], record["format"])
        if expected:
            if info["chains"] != expected:
                raise ToolFailed(
                    "STRUCTURE_SEQUENCE_MISMATCH",
                    "Predicted chain identities/coverage differ from inputs.",
                )
        if tool in DESIGN_TOOLS:
            fixed = acceptance.get("fixed_chains", {})
            if not fixed or any(info["chains"].get(k) != v for k, v in fixed.items()):
                raise ToolUnavailable(
                    "DESIGN_TARGET_REVIEW_REQUIRED",
                    "Generated design must preserve reviewed target chains.",
                )
            lengths = acceptance.get("chain_lengths", {})
            if not lengths or any(len(info["chains"].get(k, "")) != n for k, n in lengths.items()):
                raise ToolFailed(
                    "DESIGN_CHAIN_LENGTH_MISMATCH",
                    "Design chain lengths differ from the reviewed construct.",
                )
        if tool == "submit_rfdiffusion":
            lengths = acceptance.get("chain_lengths")
            if not lengths:
                raise ToolUnavailable(
                    "BACKBONE_LENGTH_REQUIRED", "Reviewed backbone chain lengths required."
                )
            if {k: len(v) for k, v in info["chains"].items()} != lengths:
                raise ToolFailed(
                    "BACKBONE_LENGTH_MISMATCH", "Generated backbone differs from reviewed lengths."
                )
        interface = None
        if acceptance.get("interface_chains"):
            a, b = acceptance["interface_chains"]
            left = [i for i, v in enumerate(atom_rows) if v[0] == a]
            right = [i for i, v in enumerate(atom_rows) if v[0] == b]
            if not left or not right:
                raise ToolFailed(
                    "INTERFACE_CHAINS_MISSING", "Both reviewed interface chains must exist."
                )
            nearest = min(float(np.linalg.norm(xyz[i] - xyz[right], axis=1).min()) for i in left)
            if nearest < 0.8 or nearest > 8:
                raise ToolFailed(
                    "INVALID_INTERFACE_GEOMETRY", "Clashing or disconnected predicted interface."
                )
            interface = {"minimum_atom_distance_angstrom": nearest, "binding": "NOT_ESTABLISHED"}
        filename = f"validated_{acceptance.get('_step_id', 'structure')}_{index}.{record['format']}"
        with (out / filename).open("x") as handle:
            handle.write(record["text"])
        checked.append(
            {**info, "filename": filename, "structure": record["text"], "interface": interface}
        )
    conf = (
        {}
        if tool in DESIGN_TOOLS
        else confidence_fields(
            docs, bool(acceptance.get("interface_chains")), checked[0]["residue_count"]
        )
    )
    for name, threshold_key in (("iptm", "minimum_iptm"), ("plddt", "minimum_plddt")):
        if threshold_key in acceptance:
            threshold = finite(
                acceptance[threshold_key], threshold_key, 0, 1 if name == "iptm" else 100
            )
            values = conf.get(name) or conf.get("ipTM" if name == "iptm" else "pLDDT")
            if not values:
                raise ToolUnavailable(
                    "ACCEPTANCE_METRIC_REQUIRED",
                    "The predeclared native confidence metric is missing.",
                )
            if any(float(np.asarray(v, dtype=float).mean()) < threshold for v in values):
                raise ToolFailed(
                    "MODEL_CONFIDENCE_QC_FAILED",
                    "Output failed its predeclared native confidence threshold.",
                )
    data.update(
        kind="backbone"
        if tool == "submit_rfdiffusion"
        else "complex"
        if acceptance.get("interface_chains")
        else "structure",
        structures=checked,
        native_confidence=conf,
    )
    if model in ("openfold2", "openfold3"):
        data["limitations"].append(
            "Portable runtime: single sequence or supplied MSA; no online temp"
            "late/MSA search or relaxation claimed."
        )
    return data
