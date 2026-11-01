"""Local trajectory/energy format and sanity checks; never asserts convergence."""

from __future__ import annotations

import csv
import io
import math
import re
from pathlib import Path

import numpy as np

from .scienceclaw.adapters.base import ToolFailed, ToolUnavailable


def energy_series(text, engine):
    """Explicit engine layouts and units; no inferred conversions."""
    if engine == "openmm":
        rows = list(csv.DictReader(io.StringIO(text)))
        # OpenMM StateDataReporter labels, including its commented first header.
        normalized = [{k.lstrip("#").strip().strip('"'): v for k, v in row.items()} for row in rows]
        fields = {
            "Time (ps)": "time_ps",
            "Potential Energy (kJ/mole)": "potential_kj_mol",
            "Temperature (K)": "temperature_k",
        }
        data = []
        for row in normalized:
            if not all(k in row for k in fields):
                raise ToolUnavailable(
                    "ENERGY_LAYOUT_UNSUPPORTED",
                    "OpenMM time, potential and temperature columns required.",
                )
            data.append({out: float(row[key]) for key, out in fields.items()})
    elif engine == "gromacs":
        # Reviewed gmx energy selection: time, Potential, Temperature, Pressure.
        labels = {
            int(i): label for i, label in re.findall(r'@\s+s(\d+)\s+legend\s+"([^"]+)"', text)
        }
        if labels != {0: "Potential", 1: "Temperature", 2: "Pressure"}:
            raise ToolUnavailable(
                "ENERGY_LAYOUT_UNSUPPORTED",
                "Expected native GROMACS Potential/Temperature/Pressure XVG.",
            )
        data = []
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith(("#", "@")):
                continue
            values = [float(x) for x in line.split()]
            if len(values) != 4:
                raise ValueError("Unexpected XVG columns")
            data.append(
                dict(
                    zip(
                        ("time_ps", "potential_kj_mol", "temperature_k", "pressure_bar"),
                        values,
                        strict=True,
                    )
                )
            )
    elif engine == "amber":
        data = []
        chunks = re.split(r"(?=\bNSTEP\s*=)", text)
        for chunk in chunks:
            time = re.search(r"TIME\(PS\)\s*=\s*(\S+)", chunk)
            temp = re.search(r"TEMP\(K\)\s*=\s*(\S+)", chunk)
            potential = re.search(r"EPtot\s*=\s*(\S+)", chunk)
            if time and temp and potential:
                data.append(
                    {
                        "time_ps": float(time[1]),
                        "temperature_k": float(temp[1]),
                        "potential_kj_mol": float(potential[1]) * 4.184,
                    }
                )
    else:
        raise ValueError("Unsupported MD engine")
    if len(data) < 2:
        raise ToolUnavailable(
            "ENERGY_SERIES_REQUIRED",
            "At least two native energy/temperature observations required.",
        )
    if not all(math.isfinite(v) for row in data for v in row.values()):
        raise ToolFailed(
            "NONFINITE_MD_ENERGY", "MD energy/time/temperature contains non-finite values."
        )
    if any(b["time_ps"] <= a["time_ps"] for a, b in zip(data, data[1:], strict=False)):
        raise ToolFailed("INVALID_MD_TIMES", "Energy times are not strictly increasing.")
    if any(row["temperature_k"] <= 0 for row in data):
        raise ToolFailed("INVALID_MD_TEMPERATURE", "Temperature must be positive Kelvin.")
    return {
        "observations": len(data),
        "start_ps": data[0]["time_ps"],
        "end_ps": data[-1]["time_ps"],
        "mean_temperature_k": float(np.mean([r["temperature_k"] for r in data])),
        "potential_energy_range_kj_mol": [
            min(r["potential_kj_mol"] for r in data),
            max(r["potential_kj_mol"] for r in data),
        ],
        "source_units": "kcal/mol converted using 4.184" if engine == "amber" else "native kJ/mol",
        "convergence": "NOT_ASSESSED",
    }


def trajectory_checks(path: Path, topology: Path, max_frames=10000):
    try:
        import mdtraj as md
    except ImportError as exc:
        raise ToolUnavailable(
            "TRAJECTORY_PARSER_REQUIRED", "Install optional MDTraj to validate trajectory formats."
        ) from exc
    frames, times, atoms = 0, [], None
    for chunk in md.iterload(str(path), top=str(topology), chunk=100):
        if (
            chunk.n_atoms <= 0
            or not np.isfinite(chunk.xyz).all()
            or not np.isfinite(chunk.time).all()
        ):
            raise ToolFailed(
                "INVALID_TRAJECTORY", "Trajectory has invalid atoms, coordinates or times."
            )
        if atoms is not None and atoms != chunk.n_atoms:
            raise ValueError("Trajectory atom count changes")
        atoms = chunk.n_atoms
        frames += chunk.n_frames
        if frames > max_frames:
            raise ToolUnavailable(
                "TRAJECTORY_AUDIT_LIMIT", "Trajectory exceeds the local full-frame audit limit."
            )
        if (
            chunk.unitcell_lengths is None
            or not np.isfinite(chunk.unitcell_lengths).all()
            or (chunk.unitcell_lengths <= 0).any()
        ):
            raise ToolFailed(
                "INVALID_PERIODIC_BOX", "Periodic trajectory box is absent or invalid."
            )
        times.extend(chunk.time.tolist())
    if frames < 2 or any(b <= a for a, b in zip(times, times[1:], strict=False)):
        raise ToolFailed(
            "INVALID_TRAJECTORY_TIMES",
            "Trajectory requires multiple strictly increasing time points.",
        )
    return {
        "format_status": "PARSED",
        "frames": frames,
        "atoms": atoms,
        "duration_ps": times[-1] - times[0],
        "coordinates": "finite nm",
        "periodic_box": "positive finite lengths",
        "equilibration": "NOT_ASSESSED",
        "convergence": "NOT_ASSESSED",
        "binding_stability": "NOT_ASSESSED",
    }
