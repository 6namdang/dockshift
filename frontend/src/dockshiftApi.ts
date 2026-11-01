/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * DockShift API adapter.
 *
 * The single seam between the team's baseline backend and the Molecular
 * Playground. Mirrors the contract the baseline frontend actually uses —
 * no invented endpoints, no renamed fields.
 *
 * The scientific point of this file: four kinds of evidence exist, they are
 * not interchangeable, and only one of them has 3D coordinates. The types
 * below keep them apart so a UI cannot accidentally render a predicted
 * potency as if it were a measured one, or draw a candidate in the binding
 * pocket when nothing ever placed it there.
 */

/* ------------------------------------------------------------------ */
/* Wire types — exactly the baseline's fields                          */
/* ------------------------------------------------------------------ */

export interface Target {
  id: string;
  name: string;
  description?: string;
  chembl_id?: string | number;
  qsar_available?: boolean;
}

export interface Prediction {
  smiles?: string;
  pubchem_cid?: number | string;
  /** QSAR model output. ~0.5 log unit error. Ranking/triage only. */
  predicted_pic50?: number | null;
  predicted_ic50_nm?: number | null;
  /** Experimental, from ChEMBL. Absent for most compounds. */
  measured_pic50?: number | null;
  measured_count?: number | null;
  /** Applicability domain. */
  max_tanimoto?: number | null;
  domain?: 'in' | 'out' | null;
  in_training_set?: boolean;
}

export interface Profile {
  qed?: number | null;
  lipinski_violations?: number | null;
  lipinski_pass?: boolean | null;
  veber_pass?: boolean | null;
  molecular_weight?: number | null;
  clogp?: number | null;
  hbd?: number | null;
  hba?: number | null;
  tpsa?: number | null;
  rotatable_bonds?: number | null;
}

export interface ShortlistEntry {
  rank: number;
  name: string;
  selected: boolean;
  note?: string;
  prediction?: Prediction;
  profile?: Profile;
}

export interface ShortlistResponse {
  target: Target;
  shortlist_size: number;
  entries: ShortlistEntry[];
}

export interface Paper {
  title: string;
  url?: string;
  doi?: string;
  source: string;
  published_date?: string;
  venue?: string;
  confidence?: number;
  authors?: string[];
  abstract?: string;
}

export interface LiteratureResponse {
  results: Paper[];
  total_hits?: Record<string, number>;
  errors?: { source: string; message: string }[];
}

/* ------------------------------------------------------------------ */
/* Async state — requirement 7                                         */
/* ------------------------------------------------------------------ */

export type Async<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; message: string }
  /** The call is valid but this data does not exist yet (e.g. docking). */
  | { status: 'unavailable'; reason: string };

export const idle = <T>(): Async<T> => ({ status: 'idle' });
export const loading = <T>(): Async<T> => ({ status: 'loading' });
export const ready = <T>(data: T): Async<T> => ({ status: 'ready', data });
export const failed = <T>(message: string): Async<T> => ({ status: 'error', message });
export const unavailable = <T>(reason: string): Async<T> => ({ status: 'unavailable', reason });

/* ------------------------------------------------------------------ */
/* Client                                                              */
/* ------------------------------------------------------------------ */

/** Matches the baseline's own rule. */
export const API_BASE =
  typeof location !== 'undefined' && location.protocol === 'file:'
    ? 'http://127.0.0.1:8000'
    : '';

/** Frontend constant in the baseline, not returned by the API. */
export const DOMAIN_THRESHOLD = 0.272;

const BACKEND_HINT =
  'Could not reach the DockShift backend. Start it with: ' +
  'uv run uvicorn app.main:app --reload';

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (e) {
    throw new Error(`${BACKEND_HINT} (${(e as Error).message})`);
  }
  const body = await res.json().catch(() => ({} as any));
  if (!res.ok) {
    const detail = (body as any)?.detail;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : detail
        ? JSON.stringify(detail).slice(0, 180)
        : `HTTP ${res.status}`
    );
  }
  return body as T;
}

export const fetchTargets = () => call<Target[]>('/api/v1/pipeline/targets');

export const runShortlist = (targetId: string, count = 6) =>
  call<ShortlistResponse>(
    `/api/v1/pipeline/${encodeURIComponent(targetId)}/shortlist` +
      `?count=${Math.max(1, Math.min(12, count))}`,
    { method: 'POST' }
  );

export const searchLiterature = (
  query: string,
  sources: string[],
  maxPerSource = 6
) =>
  call<LiteratureResponse>('/api/v1/literature/search', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      query,
      sources,
      max_results_per_source: Math.max(1, Math.min(25, maxPerSource)),
      full_text: 'never',
    }),
  });

/* ------------------------------------------------------------------ */
/* Evidence — the four classes, kept apart                             */
/* ------------------------------------------------------------------ */

export type EvidenceKind =
  | 'qsar_predicted'
  | 'chembl_measured'
  | 'experimental_structure'
  | 'docking_predicted';

export const EVIDENCE_LABEL: Record<EvidenceKind, string> = {
  qsar_predicted: 'QSAR predicted',
  chembl_measured: 'Measured (ChEMBL)',
  experimental_structure: 'Experimentally observed',
  docking_predicted: 'Docking predicted',
};

export interface PotencyEvidence {
  kind: 'qsar_predicted' | 'chembl_measured';
  pic50: number;
  ic50nM?: number | null;
  /** Caveats that apply to this number specifically. */
  caveats: string[];
}

/**
 * A deposited structure containing this ligand. Only ever non-null for a
 * compound that someone actually solved — never for a QSAR candidate.
 */
export interface StructuralEvidence {
  kind: 'experimental_structure';
  pdbId: string;
  ligandCompId: string;
  ligandName: string;
  method: string;
  resolutionA: number;
  releasedISO: string;
  /** Side-chain positions are unreliable past ~3 A. */
  sideChainCaveat?: string;
}

/**
 * Ligands with coordinates we can legitimately show in 3D.
 * Verified against RCSB before being listed here. Adding an entry is a
 * claim that the structure exists — do not add one speculatively.
 */
export const DEPOSITED_LIGANDS: Record<string, StructuralEvidence> = {
  bibr1532: {
    kind: 'experimental_structure',
    pdbId: '9Q14',
    ligandCompId: '55C',
    ligandName: 'BIBR 1532',
    method: 'Electron microscopy (single particle)',
    resolutionA: 3.0,
    releasedISO: '2026-06-17',
    sideChainCaveat:
      'At 3.00 A, side-chain positions are not reliably resolved; pocket ' +
      'detail from this structure is approximate.',
  },
};

const normalizeName = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]/g, '');

export interface Candidate {
  rank: number;
  name: string;
  shortlisted: boolean;
  note?: string;
  smiles?: string;
  pubchemCid?: number | string;
  prediction: Prediction;
  profile: Profile;
}

export function toCandidate(e: ShortlistEntry): Candidate {
  return {
    rank: e.rank,
    name: e.name,
    shortlisted: !!e.selected,
    note: e.note,
    smiles: e.prediction?.smiles,
    pubchemCid: e.prediction?.pubchem_cid,
    prediction: e.prediction ?? {},
    profile: e.profile ?? {},
  };
}

export const toCandidates = (r: ShortlistResponse): Candidate[] =>
  (r.entries ?? []).map(toCandidate);

/** Potency evidence present for this candidate. Never fabricates. */
export function potencyEvidence(c: Candidate): PotencyEvidence[] {
  const p = c.prediction;
  const out: PotencyEvidence[] = [];

  if (p.predicted_pic50 != null) {
    const caveats = ['QSAR prediction, about 0.5 log unit of error — for ranking and triage'];
    if (p.domain === 'out') {
      caveats.push(
        `Outside the applicability domain (max Tanimoto ` +
          `${p.max_tanimoto?.toFixed(2) ?? '?'} < ${DOMAIN_THRESHOLD}) — extrapolation`
      );
    }
    if (p.in_training_set) {
      caveats.push('In the training set — this prediction is optimistic');
    }
    out.push({
      kind: 'qsar_predicted',
      pic50: p.predicted_pic50,
      ic50nM: p.predicted_ic50_nm,
      caveats,
    });
  }

  if (p.measured_pic50 != null) {
    out.push({
      kind: 'chembl_measured',
      pic50: p.measured_pic50,
      caveats: [
        `Experimental value from ChEMBL` +
          (p.measured_count ? ` (${p.measured_count} measurement${p.measured_count > 1 ? 's' : ''})` : ''),
      ],
    });
  }

  return out;
}

/**
 * The ONLY route to 3D coordinates.
 *
 * Returns null unless this exact compound has a deposited structure. A
 * candidate that came out of the QSAR shortlist has no pose, because
 * nothing has placed it in the pocket. Gate every Mol* ligand
 * representation on this returning non-null.
 */
export function structuralEvidence(c: Candidate): StructuralEvidence | null {
  return DEPOSITED_LIGANDS[normalizeName(c.name)] ?? null;
}

/**
 * Docking is not wired up yet. Returns `unavailable` rather than a number,
 * so the UI renders an honest empty state instead of a placeholder score.
 * When the docking pipeline lands, replace the body — not the signature,
 * and not the QSAR fields.
 */
export function dockingEvidence(_c: Candidate): Async<never> {
  return unavailable('Docking has not been run for this candidate yet.');
}

/** 2D depiction only. Deliberately separate from structuralEvidence(). */
export function depictionUrl(c: Candidate): string | null {
  if (c.pubchemCid == null) return null;
  return (
    `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/` +
    `${c.pubchemCid}/PNG?image_size=160x160`
  );
}

/* ------------------------------------------------------------------ */
/* Derived display helpers (mirror the baseline's own rules)           */
/* ------------------------------------------------------------------ */

export interface Badge {
  tone: 'good' | 'warn' | 'info';
  label: string;
  title?: string;
}

export function badgesFor(c: Candidate): Badge[] {
  const p = c.prediction, pr = c.profile, b: Badge[] = [];
  if (p.domain) {
    b.push(
      p.domain === 'in'
        ? { tone: 'good', label: 'In domain', title: `max Tanimoto ${p.max_tanimoto?.toFixed(2)} >= ${DOMAIN_THRESHOLD}` }
        : { tone: 'warn', label: 'Outside domain', title: `max Tanimoto ${p.max_tanimoto?.toFixed(2)} < ${DOMAIN_THRESHOLD} — extrapolation` }
    );
  }
  if (p.in_training_set) {
    b.push({ tone: 'info', label: 'In training set', title: 'The model was fitted on this compound, so its prediction is optimistic.' });
  }
  if (p.measured_pic50 != null) {
    b.push({ tone: 'info', label: `Measured ${p.measured_pic50.toFixed(2)}`, title: 'Experimental pIC50 from ChEMBL' });
  }
  if (pr.lipinski_violations != null) {
    b.push({ tone: pr.lipinski_pass ? 'good' : 'warn', label: `Lipinski ${pr.lipinski_violations}` });
  }
  if (pr.veber_pass != null) {
    b.push({ tone: pr.veber_pass ? 'good' : 'warn', label: pr.veber_pass ? 'Veber pass' : 'Veber fail' });
  }
  if (structuralEvidence(c)) {
    const s = structuralEvidence(c)!;
    b.push({ tone: 'info', label: `PDB ${s.pdbId}`, title: `${s.ligandName} observed in ${s.pdbId} (${s.resolutionA} A)` });
  }
  return b;
}

export interface Meter {
  label: string;
  value: number | null | undefined;
  max: number;
  caption?: string;
  mark?: number;
}

export function metersFor(c: Candidate): Meter[] {
  const m: Meter[] = [];
  if (c.prediction.max_tanimoto != null) {
    m.push({
      label: 'Similarity to training set',
      value: c.prediction.max_tanimoto,
      max: 1,
      caption: `Tick marks the ${DOMAIN_THRESHOLD} domain threshold`,
      mark: DOMAIN_THRESHOLD,
    });
  }
  if (c.profile.qed != null) {
    m.push({ label: 'Drug-likeness (QED)', value: c.profile.qed, max: 1, caption: '0 = poor, 1 = ideal' });
  }
  return m;
}

export function propertyLine(c: Candidate): string | null {
  const p = c.profile;
  if (p.molecular_weight == null) return null;
  return `MW ${p.molecular_weight} · cLogP ${p.clogp} · HBD ${p.hbd} · HBA ${p.hba} · TPSA ${p.tpsa} · rot. bonds ${p.rotatable_bonds}`;
}
