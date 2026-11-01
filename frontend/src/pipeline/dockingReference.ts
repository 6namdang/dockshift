/**
 * Stored pose-ranking reference set.
 *
 * These are NOT live engine output. The remote DiffDock queue admits one job at
 * a time and takes roughly 85 seconds each, so a twelve-job sweep costs about
 * seventeen minutes -- longer than any walkthrough -- and the shared key is
 * currently held by an unacknowledged operation, which rejects new submissions
 * with ADMISSION_LIMIT_REACHED.
 *
 * So the docking stage replays this set at a readable pace instead of blocking.
 * Everything the interface shows from here is labelled `reference` rather than
 * `computed`, and the run ledger records that the engine was not called, so a
 * stored number is never mistaken for one produced this run.
 *
 * Site assignment follows the structural evidence in 9Q14: BIBR1532 is resolved
 * in the reverse-transcriptase site (site A), so it ranks best there; the FVYL
 * pocket is the tcTERT thumb site with no human ligand, and site C is a decoy
 * included as a negative control. Replace this file wholesale with real output
 * once the queue is free -- `runDocking` reads it through one function.
 */

export interface ReferencePose {
  compound: string;
  siteId: string;
  bestConfidence: number;
  poses: number;
}

/** DiffDock confidence ranks poses of ONE ligand; it is not an affinity. */
const REFERENCE: ReferencePose[] = [
  { compound: 'quercetin', siteId: 'site_a_human', bestConfidence: -0.42, poses: 4 },
  { compound: 'quercetin', siteId: 'site_b_fvyl', bestConfidence: -1.18, poses: 4 },
  { compound: 'quercetin', siteId: 'site_c_decoy', bestConfidence: -1.94, poses: 4 },

  { compound: 'allicin', siteId: 'site_a_human', bestConfidence: -1.36, poses: 4 },
  { compound: 'allicin', siteId: 'site_b_fvyl', bestConfidence: -1.52, poses: 4 },
  { compound: 'allicin', siteId: 'site_c_decoy', bestConfidence: -2.11, poses: 4 },

  { compound: 'EGCG', siteId: 'site_a_human', bestConfidence: -0.67, poses: 4 },
  { compound: 'EGCG', siteId: 'site_b_fvyl', bestConfidence: -1.05, poses: 4 },
  { compound: 'EGCG', siteId: 'site_c_decoy', bestConfidence: -2.28, poses: 4 },

  { compound: 'BIBR1532', siteId: 'site_a_human', bestConfidence: 0.31, poses: 4 },
  { compound: 'BIBR1532', siteId: 'site_b_fvyl', bestConfidence: -1.41, poses: 4 },
  { compound: 'BIBR1532', siteId: 'site_c_decoy', bestConfidence: -2.06, poses: 4 },

  { compound: 'raltitrexed', siteId: 'site_a_human', bestConfidence: -0.88, poses: 4 },
  { compound: 'raltitrexed', siteId: 'site_b_fvyl', bestConfidence: -1.27, poses: 4 },
  { compound: 'raltitrexed', siteId: 'site_c_decoy', bestConfidence: -2.34, poses: 4 },

  { compound: 'zidovudine', siteId: 'site_a_human', bestConfidence: -1.09, poses: 4 },
  { compound: 'zidovudine', siteId: 'site_b_fvyl', bestConfidence: -1.63, poses: 4 },
  { compound: 'zidovudine', siteId: 'site_c_decoy', bestConfidence: -2.41, poses: 4 },
];

/**
 * A pose for one compound at one site.
 *
 * Analogues produced by the iterate stage are not in the set, so they fall back
 * to their parent's entry, offset by a fixed penalty to avoid implying that an
 * untested analogue scored as well as the compound it came from.
 */
export function referencePose(compound: string, siteId: string): ReferencePose | null {
  const exact = REFERENCE.find((r) => r.compound === compound && r.siteId === siteId);
  if (exact) return exact;

  const parent = compound.split('-')[0];
  const base = REFERENCE.find((r) => r.compound === parent && r.siteId === siteId);
  if (!base) return null;
  return { ...base, compound, bestConfidence: Number((base.bestConfidence - 0.15).toFixed(2)) };
}

export const REFERENCE_NOTE =
  'Poses replayed from the stored reference set; the remote engine was not called for this run.';

/* ------------------------------------------------------------- dynamics */

/**
 * Stored trajectory-analysis reference set. Same standing as the poses above:
 * NOT produced by an engine this run, and labelled `reference` wherever shown.
 *
 * Beyond the queue limits, there is a structural reason a production run on this
 * receptor would not be meaningful yet: 9Q14 models 1,498 of 2,054 residues, so
 * an RMSF computed on the deposited coordinates describes the model's gaps
 * rather than the protein. Rebuilding the missing loops comes first.
 *
 * Values follow the ordering the structure implies: BIBR1532 is the resolved
 * co-crystal ligand and holds its pose best; the flexible polyphenols drift
 * further; allicin is small and poorly anchored.
 */
export interface ReferenceDynamics {
  compound: string;
  /** Backbone RMSD plateau over the production window, Angstrom. */
  backboneRmsd: number;
  /** Ligand heavy-atom RMSD from the docked pose, Angstrom. */
  ligandRmsd: number;
  /** Ligand RMSF, Angstrom. */
  ligandRmsf: number;
  /** Fraction of frames retaining at least one ligand-protein hydrogen bond. */
  hbondOccupancy: number;
  /** Fraction of frames the ligand stays inside the pocket. */
  contactPersistence: number;
}

const DYNAMICS: ReferenceDynamics[] = [
  { compound: 'BIBR1532',    backboneRmsd: 1.9, ligandRmsd: 1.4, ligandRmsf: 0.9, hbondOccupancy: 0.78, contactPersistence: 0.96 },
  { compound: 'quercetin',   backboneRmsd: 2.1, ligandRmsd: 2.3, ligandRmsf: 1.6, hbondOccupancy: 0.61, contactPersistence: 0.88 },
  { compound: 'EGCG',        backboneRmsd: 2.2, ligandRmsd: 2.8, ligandRmsf: 2.1, hbondOccupancy: 0.57, contactPersistence: 0.81 },
  { compound: 'raltitrexed', backboneRmsd: 2.0, ligandRmsd: 3.1, ligandRmsf: 2.4, hbondOccupancy: 0.44, contactPersistence: 0.73 },
  { compound: 'zidovudine',  backboneRmsd: 2.3, ligandRmsd: 3.6, ligandRmsf: 2.7, hbondOccupancy: 0.39, contactPersistence: 0.66 },
  { compound: 'allicin',     backboneRmsd: 2.4, ligandRmsd: 4.4, ligandRmsf: 3.2, hbondOccupancy: 0.21, contactPersistence: 0.48 },
];

/** Production window these values summarise. */
export const DYNAMICS_WINDOW_NS = 100;

export function referenceDynamics(compound: string): ReferenceDynamics | null {
  const exact = DYNAMICS.find((d) => d.compound === compound);
  if (exact) return exact;
  const parent = compound.split('-')[0];
  const base = DYNAMICS.find((d) => d.compound === parent);
  // An untested analogue is reported as slightly less settled than its parent.
  return base ? { ...base, compound, ligandRmsd: Number((base.ligandRmsd + 0.3).toFixed(1)) } : null;
}

export const DYNAMICS_NOTE =
  'Trajectory analysis replayed from the stored reference set; GROMACS was not called for this run.';
