"""Conservative receptor and RDKit/Open Babel ligand preparation."""

from __future__ import annotations

import asyncio
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem

from app.config import Settings
from app.structural.artifacts import ArtifactStore, RunWorkspace
from app.structural.errors import ArtifactError
from app.structural.execution import LocalExecutionBackend
from app.structural.models import (
    LigandPreparationRequest,
    LigandPreparationResult,
    ReceptorPreparationRequest,
    ReceptorPreparationResult,
    RunStatus,
)

_WATER_RESIDUES = {"HOH", "WAT", "H2O"}


class PreparationService:
    def __init__(
        self, settings: Settings, store: ArtifactStore, backend: LocalExecutionBackend
    ) -> None:
        self.settings = settings
        self.store = store
        self.backend = backend

    async def prepare_ligand(self, request: LigandPreparationRequest) -> LigandPreparationResult:
        workspace = self.store.create_run("prepare-ligand")
        molecule, canonical, force_field, warnings, optimization_status = await asyncio.to_thread(
            self._prepare_ligand_molecule, request
        )
        sdf_path = workspace.path / "ligand.sdf"
        pdb_path = workspace.path / "ligand.pdb"
        writer = Chem.SDWriter(str(sdf_path))
        writer.write(molecule)
        writer.close()
        Chem.MolToPDBFile(molecule, str(pdb_path))
        pdbqt_path = workspace.path / "ligand.pdbqt"
        output = await self.backend.run(
            self.settings.obabel_executable,
            [str(sdf_path), "-O", str(pdbqt_path)],
            workspace,
            label="Open-Babel-ligand",
        )
        if not pdbqt_path.is_file() or pdbqt_path.stat().st_size == 0:
            raise ArtifactError("Open Babel did not create a ligand PDBQT file.")
        sdf_ref = self.store.ref(sdf_path, media_type="chemical/x-mdl-sdfile")
        pdb_ref = self.store.ref(pdb_path, media_type="chemical/x-pdb")
        pdbqt_ref = self.store.ref(pdbqt_path, media_type="chemical/x-pdbqt")
        return LigandPreparationResult(
            run_id=workspace.run_id,
            status=RunStatus.SUCCESS,
            engine="RDKit + Open Babel",
            engine_version=output.summary.version,
            artifacts=[sdf_ref, pdb_ref, pdbqt_ref],
            warnings=warnings,
            command=output.summary,
            provenance={
                "source": request.smiles if request.smiles is not None else request.sdf.path,
                "hydrogens_added": True,
                "optimization_requested": request.optimize,
                "optimization_status": optimization_status,
                "optimized": optimization_status == "converged",
                "random_seed": request.random_seed,
            },
            name=request.name,
            canonical_smiles=canonical,
            force_field=force_field,
            sdf=sdf_ref,
            pdb=pdb_ref,
            pdbqt=pdbqt_ref,
        )

    def _prepare_ligand_molecule(
        self, request: LigandPreparationRequest
    ) -> tuple[Chem.Mol, str, str | None, list[str], str]:
        warnings: list[str] = []
        if request.smiles is not None:
            molecule = Chem.MolFromSmiles(request.smiles)
            if molecule is None:
                raise ArtifactError("RDKit could not parse the ligand SMILES.")
        else:
            assert request.sdf is not None
            source = self.store.resolve_input(request.sdf.path)
            supplier = Chem.SDMolSupplier(str(source), removeHs=False)
            molecule = next((mol for mol in supplier if mol is not None), None)
            if molecule is None:
                raise ArtifactError("RDKit could not read a molecule from the SDF input.")
        canonical = Chem.MolToSmiles(Chem.RemoveHs(molecule), canonical=True)
        molecule = Chem.AddHs(molecule, addCoords=True)
        needs_embedding = molecule.GetNumConformers() == 0 or not molecule.GetConformer().Is3D()
        if needs_embedding:
            parameters = AllChem.ETKDGv3()
            parameters.randomSeed = request.random_seed
            if AllChem.EmbedMolecule(molecule, parameters) != 0:
                raise ArtifactError("RDKit failed to generate a 3D ligand conformer.")
        force_field: str | None = None
        optimization_status = "not_requested"
        if request.optimize:
            try:
                if AllChem.MMFFHasAllMoleculeParams(molecule):
                    result = AllChem.MMFFOptimizeMolecule(molecule)
                    force_field = "MMFF94"
                elif AllChem.UFFHasAllMoleculeParams(molecule):
                    result = AllChem.UFFOptimizeMolecule(molecule)
                    force_field = "UFF"
                    warnings.append("MMFF parameters were unavailable; RDKit used UFF.")
                else:
                    result = None
                    optimization_status = "parameters_unavailable"
                    warnings.append(
                        "No complete MMFF/UFF parameters were available; "
                        "geometry was not optimized."
                    )
            except Exception as exc:
                raise ArtifactError(
                    f"RDKit force-field optimization failed: {type(exc).__name__}."
                ) from exc
            if result == 0:
                optimization_status = "converged"
            elif result == 1:
                optimization_status = "not_converged"
                warnings.append(
                    f"RDKit {force_field} optimization reached its iteration limit without "
                    "convergence; the generated geometry is retained for explicit review."
                )
            elif result is not None:
                raise ArtifactError(
                    f"RDKit {force_field} optimization failed with status {result}."
                )
        return molecule, canonical, force_field, warnings, optimization_status

    async def prepare_receptor(
        self, request: ReceptorPreparationRequest
    ) -> ReceptorPreparationResult:
        workspace = self.store.create_run("prepare-receptor")
        source = self.store.resolve_input(request.structure.path)
        pdb_source = await self._ensure_pdb(source, workspace)
        cleaned_path = workspace.path / "receptor.cleaned.pdb"
        warnings = await asyncio.to_thread(
            self._clean_pdb,
            pdb_source,
            cleaned_path,
            request.remove_waters,
            request.remove_heterogens,
            request.remove_alternate_locations,
        )
        pdbqt_path = workspace.path / "receptor.pdbqt"
        output = await self.backend.run(
            self.settings.obabel_executable,
            [str(cleaned_path), "-O", str(pdbqt_path), "-xr"],
            workspace,
            label="Open-Babel-receptor",
        )
        if not pdbqt_path.is_file() or pdbqt_path.stat().st_size == 0:
            raise ArtifactError("Open Babel did not create a receptor PDBQT file.")
        warnings.append(
            "Inspect receptor protonation, atom types, metals, cofactors, missing residues, "
            "and alternate states before scientific use. Automated cleanup is intentionally "
            "conservative."
        )
        cleaned_ref = self.store.ref(cleaned_path, media_type="chemical/x-pdb")
        pdbqt_ref = self.store.ref(pdbqt_path, media_type="chemical/x-pdbqt")
        return ReceptorPreparationResult(
            run_id=workspace.run_id,
            status=RunStatus.SUCCESS,
            engine="Open Babel rigid-receptor preparation",
            artifacts=[cleaned_ref, pdbqt_ref],
            warnings=warnings,
            command=output.summary,
            provenance=request.model_dump(mode="json"),
            cleaned_structure=cleaned_ref,
            pdbqt=pdbqt_ref,
        )

    async def _ensure_pdb(self, source: Path, workspace: RunWorkspace) -> Path:
        if source.suffix.lower() in {".pdb", ".ent"}:
            return self.store.copy_input(source, workspace.path, name="receptor.source.pdb")
        if source.suffix.lower() not in {".cif", ".mmcif"}:
            raise ArtifactError("Receptor input must be PDB, CIF, or mmCIF.")
        converted = workspace.path / "receptor.source.pdb"
        await self.backend.run(
            self.settings.obabel_executable,
            [str(source), "-O", str(converted)],
            workspace,
            label="Open-Babel-mmCIF-conversion",
        )
        if not converted.is_file():
            raise ArtifactError("Open Babel did not convert the receptor to PDB.")
        return converted

    @staticmethod
    def _clean_pdb(
        source: Path,
        destination: Path,
        remove_waters: bool,
        remove_heterogens: bool,
        remove_alternate_locations: bool,
    ) -> list[str]:
        output: list[str] = []
        removed_waters = 0
        removed_heterogens = 0
        removed_alternates = 0
        atom_count = 0
        for raw_line in source.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.ljust(80)
            record = line[:6].strip()
            if record not in {"ATOM", "HETATM"}:
                output.append(raw_line)
                continue
            residue = line[17:20].strip().upper()
            if remove_waters and residue in _WATER_RESIDUES:
                removed_waters += 1
                continue
            if remove_heterogens and record == "HETATM":
                removed_heterogens += 1
                continue
            alt_location = line[16]
            if remove_alternate_locations and alt_location not in {" ", "A"}:
                removed_alternates += 1
                continue
            if remove_alternate_locations and alt_location == "A":
                line = f"{line[:16]} {line[17:]}"
            output.append(line.rstrip())
            atom_count += 1
        if atom_count == 0:
            raise ArtifactError("Receptor cleanup produced no atoms.")
        destination.write_text("\n".join(output) + "\n", encoding="utf-8")
        warnings = []
        if removed_waters:
            warnings.append(f"Removed {removed_waters} water atoms/records.")
        if removed_heterogens:
            warnings.append(
                f"Removed {removed_heterogens} heterogen atoms/records, including possible "
                "cofactors or metals."
            )
        if removed_alternates:
            warnings.append(f"Removed {removed_alternates} non-primary alternate-location atoms.")
        return warnings
