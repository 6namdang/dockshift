/**
 * The only place the pipeline talks to the backend.
 *
 * Every call here hits a route that exists. Where a stage cannot run — because an
 * engine is unreachable or a prerequisite is missing — the call reports that
 * rather than substituting a value.
 */

import type { CandidateRow } from './types';

const BASE =
  typeof location !== 'undefined' && location.protocol === 'file:'
    ? 'http://127.0.0.1:8000'
    : '';

export class ApiError extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch (e) {
    throw new ApiError(
      `Backend unreachable. Start it with: uv run uvicorn app.main:app --reload (${(e as Error).message})`
    );
  }
  const body = await res.json().catch(() => ({}) as unknown);
  if (!res.ok) {
    const detail = (body as { detail?: unknown })?.detail;
    throw new ApiError(
      typeof detail === 'string'
        ? detail
        : detail
          ? JSON.stringify(detail).slice(0, 200)
          : `HTTP ${res.status}`
    );
  }
  return body as T;
}

/* ---------------------------------------------------------------- targets */

export interface TargetDto {
  id: string;
  name: string;
  description?: string;
  chembl_id?: string;
  qsar_available?: boolean;
}

export const fetchTargets = () => call<TargetDto[]>('/api/v1/pipeline/targets');

/* ------------------------------------------------------------- candidates */

interface PredictionDto {
  smiles?: string;
  predicted_pic50?: number | null;
  predicted_ic50_nm?: number | null;
  measured_pic50?: number | null;
  max_tanimoto?: number | null;
  domain?: 'in' | 'out' | null;
  in_training_set?: boolean;
}

interface ProfileDto {
  qed?: number | null;
  lipinski_violations?: number | null;
  veber_pass?: boolean | null;
  molecular_weight?: number | null;
  clogp?: number | null;
}

interface ShortlistEntryDto {
  rank: number;
  name: string;
  note?: string;
  selected: boolean;
  prediction?: PredictionDto;
  profile?: ProfileDto;
}

export interface ShortlistDto {
  target: TargetDto;
  entries: ShortlistEntryDto[];
  shortlist_size: number;
  chemotypes?: number | null;
  similarity?: (number | null)[][];
}

export const runShortlist = (targetId: string, count = 6) =>
  call<ShortlistDto>(
    `/api/v1/pipeline/${encodeURIComponent(targetId)}/shortlist?count=${count}`,
    { method: 'POST' }
  );

export function toRows(dto: ShortlistDto): CandidateRow[] {
  return dto.entries.map((e) => ({
    rank: e.rank,
    name: e.name,
    note: e.note,
    smiles: e.prediction?.smiles,
    predictedPic50: e.prediction?.predicted_pic50 ?? null,
    predictedIc50Nm: e.prediction?.predicted_ic50_nm ?? null,
    measuredPic50: e.prediction?.measured_pic50 ?? null,
    maxTanimoto: e.prediction?.max_tanimoto ?? null,
    domain: e.prediction?.domain ?? null,
    inTrainingSet: e.prediction?.in_training_set ?? false,
    qed: e.profile?.qed ?? null,
    lipinskiViolations: e.profile?.lipinski_violations ?? null,
    veberPass: e.profile?.veber_pass ?? null,
    molecularWeight: e.profile?.molecular_weight ?? null,
    clogp: e.profile?.clogp ?? null,
    selected: e.selected,
  }));
}

/* --------------------------------------------------------------- scoring */

export interface ActivityDto {
  predictions: (PredictionDto & { query: string; error?: string | null })[];
  domain_threshold: number;
}

export const predictActivity = (compounds: string[]) =>
  call<ActivityDto>('/api/v1/qsar/htert/predict', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(compounds),
  });

export const profileCompounds = (compounds: string[]) =>
  call<{ profiles: (ProfileDto & { query: string })[] }>('/api/v1/qsar/htert/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(compounds),
  });

/* ------------------------------------------------------- remote engines */

export interface EngineDto {
  tool: string;
  label: string;
  available: boolean;
  description?: string;
}

export interface EngineStatusDto {
  configured: boolean;
  reachable: boolean;
  endpoint: string;
  total_tools: number;
  engines: EngineDto[];
  error?: string | null;
}

export const fetchEngines = () => call<EngineStatusDto>('/api/v1/remote/engines');

export interface SiteDto {
  id: string;
  name: string;
  description: string;
  centroid: [number, number, number];
}

export const fetchSites = () =>
  call<{ receptor: string; sites: SiteDto[] }>('/api/v1/remote/sites');

/* --------------------------------------------------------------- docking */

export interface DockRunDto {
  site: SiteDto;
  compound: string;
  ligand: string;
  status: string;
  best_confidence: number | null;
  poses: number;
  operation_id?: string | null;
  error?: string | null;
}

export interface ThreeSiteDto {
  receptor: string;
  compounds: string[];
  sites: SiteDto[];
  runs: DockRunDto[];
  note: string;
}

/** Dock the chosen compounds at all three sites on the receptor. */
export const threeSiteDock = (compounds: Record<string, string>, radius = 18) =>
  call<ThreeSiteDto>(`/api/v1/remote/three-site-dock?radius=${radius}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ compounds }),
  });

/** The route rejects anything under 80px, so clamp rather than let a caller 422. */
export const structureSvgUrl = (smiles: string, size = 180) =>
  `${BASE}/api/v1/qsar/htert/structure?size=${Math.min(600, Math.max(80, Math.round(size)))}` +
  `&smiles=${encodeURIComponent(smiles)}`;
