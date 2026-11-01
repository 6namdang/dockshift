# hTERT/BIBR1532 scientific preparation (no remote computation)

This records the initial preparation stage. Current collective workflow, verification
and team startup instructions are in [DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md).

The added preparation workflow runs the existing eight-worker runtime with LLM
inference forcibly disabled. It uses public RCSB records, Nebius tool/schema
reads and inexpensive local RDKit checks. It does not submit models, upload
files, repair structures, invent parameters or enable computation gates.

```sh
cd backend
uv run python -m app.integration.prepare_science
```

The authenticated API alternative is `POST
/api/v1/agents/preparations/htert-bibr1532` (HTTP 202). Existing progress,
report and verified artifact-download endpoints work for the resulting run ID.
Preparation itself does not require AGENT_COMPUTE_ENABLED, AGENT_ADMET_ENABLED,
AGENT_LLM_ENABLED or Token Factory. The existing API authentication gate still
applies; this work has not enabled or changed it.

## Actual prepared evidence

A real read-only preparation run was saved as
`agents-afa5ea3f586d42648a1672e65fb2c02b` beneath the ignored
`backend/.dockshift-agent-runs/` root. Existing scientific results were preserved.
Its report and manifest verify the source and generated file hashes.

- Live RCSB entry 9Q14, chemical component 55C and polymer-entity records map
  hTERT accession O14746 to author chain A.
- `source_9Q14.pdb`, RCSB metadata and CCD chemistry snapshots are retained.
- `receptor_htert.pdb`: complete deposited protein chain A, 7,634 atom records
  and 951 observed residues. This preparation does not reuse the candidate
  workflow's spatial crop. It does not create missing atoms or residues.
- `reference_55C.pdb` and `reference_55C.sdf`: actual deposited coordinates;
  RDKit restores CCD bond orders and checks stereo/chemical identity. The
  ligand contains 25 heavy atoms; the neutral CCD structure's InChIKey is
  `PGFQXGLPJUCTOI-WYMLVPIESA-N`.
- The chain spans residue numbering 1–1132 with 181 unobserved internal residues
  at 105–116, 179–321 and 417–442. These are not repaired or silently capped.
- `diffdock_arguments.json` passes the current discovered input schema. It
  specifies the exact receptor bytes, CCD canonical ligand SMILES, four poses,
  seed 2026, zero inline wait and an idempotency key. No operation was submitted.
- `docking_plan.json` binds receptor, reference SDF and argument file hashes;
  its status is PREPARED_REVIEW_REQUIRED. The full run remains BLOCKED.

A1 performs primary-record acquisition, A2 the structural/coordinate audit,
A3 the reference chemistry audit, A5a schema/request preparation, A6 the MD
prerequisite/protocol audit, and A7 the independent integrity/completeness
review. A4/A5b remain blocked because no biologic design is requested.
Preparation success is distinct from docking or simulation execution.

The original team receptor, docking, QSAR, literature, structural and frontend
modules are unchanged. All behavior is in added integration adapters, with
small extensions to the existing integration-owned models/runtime/routes.

## DiffDock execution gate and result checks

Candidate docking now requires a sealed `docking_preparation_id`, a nonempty
`docking_reviewed_by` attestation, exact matching candidate identity and a
separate expensive-compute authorization. A resume can poll an existing
operation without turning submission back on. The prepared reference workflow
currently supports BIBR1532 redocking only; another ligand needs its own plan.

Before approval, review the missing loops/termini, atom completeness, alternate
states, ligand protonation and the experimental assembly. RNA, DNA, accessory
proteins, waters and heterogens are excluded from this protein-only DiffDock
input and retained in the raw experimental source. The neutral CCD microstate
is not a pH-dependent MD protonation assignment. No docked pose or affinity
has been computed in this work.

The added native SDF validator checks finite 3D coordinates, graph/stereo
identity, actual confidence/pose pairs and a symmetry-aware **unaligned** RMSD
in the deposited receptor frame. The predeclared reference-QC threshold is
2.0 Å. A shifted pose cannot pass by fitting it onto the reference. Failing
reference QC produces FAILED, not a successful validated docking result.
DiffDock confidence is never converted to Vina energy, pIC50 or affinity.
Unsupported output shapes remain blocked instead of being approximated.

## MD schemas and preparation status

Current GROMACS, AMBER and OpenMM schemas were read from the configured Nebius
server and snapshotted with the preparation. Frozen copies under
`backend/tests/fixtures/nebius/` support offline contract regression tests;
live discovery remains authoritative before execution.

| Engine | Required native scientific input | Provider qualification observed |
|---|---|---|
| GROMACS | Solvated coordinates, topol.top, every referenced include, staged MDP files; exact native grompp/mdrun argv | isolated-pilot |
| AMBER | Parameterized PRMTOP, INPCRD/restart, MDIN stages and expected native step counts | source-adapter-awaiting-live-qualification |
| OpenMM | Prepared AMBER/GROMACS topology and coordinates, or fully supported PDB component templates; typed integrator/ensemble steps | source-adapter-awaiting-live-qualification |

GROMACS/AMBER input files and OpenMM native parameter JSON were generated as
**drafts** and validated against the exact advertised parameter schemas.
They propose minimization, 20 ps NVT, 50 ps NPT and a 1 ns pilot production
run at 300 K (1 bar in NPT/production), 2 fs dynamics timestep and explicit
seeds. These durations are not evidence of equilibration or convergence.
The proposed compatible AMBER-family route is ff14SB protein, OL3 RNA, OL15
DNA, TIP3P water/matched ions and GAFF2/AM1-BCC ligand parameters. This is a
proposal for scientist review, not a selected or executed force field.

No simulation-ready system or ligand parameters have been generated. The backend
environment lacks AmberTools (antechamber/parmchk2/tleap), GROMACS, OpenMM,
OpenMM force-field extensions, ParmEd, PDBFixer and Open Babel. RDKit is present.
RDKit geometry or a docking SDF does not substitute for MD partial charges,
atom types, bonded/nonbonded parameters or a native solvated topology.

Remaining physical prerequisites:

1. Review the full intended protein/RNA/DNA/accessory assembly, repair or justify
   unresolved regions and termini, and choose a reviewed reference/docked pose.
2. Select ligand/protein/nucleic-acid protonation and tautomers at the intended
   pH; determine ligand charge. No charge was assumed for AM1-BCC calculations.
3. Generate and inspect real ligand MOL2/GAFF2 atom types and AM1-BCC charges,
   FRCMOD terms and compatibility with macromolecular/water/ion parameters.
4. Build the complete topology and coordinates, check atom ordering, include
   closure, charge neutrality and all cofactor/metal terms, then solvate/ionize.
5. Review restraint, thermostat, barostat, cutoffs, constraints, timestep,
   equilibration and production choices, and complete native preprocessing.
6. Publish a real immutable scientific input manifest and bundle after review.
   No artifact IDs, parameters, topologies or precheck results are fabricated.
7. Obtain scientific signoff, provider qualification and compute/budget approval.

The new A6 adapter requires a hashed local MD review manifest, actual native
files and ligand parameters, declared component force fields, ligand charge
consistency and hashed native-precheck evidence. It checks safe bundle contents
against reviewed files and binds the remote input manifest to the local archive.
Requested completion counts are derived from the submitted native protocols.
An arbitrary readiness flag or a declared force-field name is insufficient.
The schema is `dockshift-md-system/v1`; `md_review` holds its input-root file
reference, digest and reviewer. This is an admission audit, not an automatic
physical-validity certificate.

Binary artifacts can now be retrieved and hash-verified without forcing them
through a JSON parser. Native result validation requires explicit success,
engine/model version, matching completed step counts and retained trajectory
bytes. Unsupported native result layouts remain blocked pending a verified
engine-specific parser. Trajectory byte integrity does not establish trajectory
format quality, equilibration, binding stability or experimental efficacy;
those scientific assessments remain NOT_ASSESSED.

## Local verification and primary references

Tests use synthetic structures/poses and frozen schemas, never real remote
inference. They cover chemistry mismatches, coordinate-frame RMSD, failed QC,
missing topology/parameters, unsafe archives, input-bound step counts,
non-finite results, missing trajectories, binary transport, and a complete
preparation run that refuses any scientific model or LLM invocation.

- [RCSB 9Q14](https://www.rcsb.org/structure/9Q14)
- [RCSB chemical component 55C](https://www.rcsb.org/ligand/55C)
- [AMBER ligand preparation guidance](https://ambermd.org/tutorials/basic/tutorial4b/)
- [OpenMM system and force-field guidance](https://docs.openmm.org/latest/userguide/application/02_running_sims.html)
- [GROMACS topology guidance](https://manual.gromacs.org/current/how-to/topology.html)

## Verification and scope of this stage

Local verification: 52 backend tests, 7 frontend tests, Ruff and TypeScript
checks passed. The production build passed with Node 22.23.4; the default
Node 18 cannot build the existing Vite toolchain. Existing Vite/3Dmol bundle
warnings remain. No live docking/MD result parser was qualified by these tests.

This stage changes only integration adapters/tests/documentation and adds one
integration route. No frontend or original scientific module changes were
needed. Compared with `origin/main`, the earlier integration checkpoint also
modified these original team files, which this stage preserves:

| Original files | Reason for earlier integration change |
|---|---|
| README.md | Integrated setup and execution instructions |
| backend/.env.example, backend/.gitignore | Non-secret settings and ignored runtime artifacts |
| backend/app/config.py | Runtime paths, limits, provider settings and disabled-by-default gates |
| backend/app/main.py | Register integration service/routes and lifecycle cleanup |
| backend/app/nebius/client.py | Expose native schemas and opt-in pending-operation handling |
| backend/pyproject.toml, backend/uv.lock | Schema validation/test dependencies and reproducible lock |
| frontend/src/App.tsx, frontend/src/components/NavigationSidebar.tsx | Add collective runtime navigation/view |
| frontend/src/dockshiftApi.ts | Authenticated integration API client |
| frontend/package.json | Frontend regression test command |
| frontend/dist/index.html | Previously tracked build entry from integration build |

The previously tracked backend/.env is removed from the integration branch's
tracked source; its ignored local copy was not changed by this stage. No keys
are included in the new changes. Agentic_System_Test and the original dockshift
workspace match their saved source/HEAD/status snapshots. No commit, push or
merge was performed.
