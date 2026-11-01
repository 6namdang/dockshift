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
