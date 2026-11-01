import { API_BASE, AgentRunResult, AgentCapabilities, Prediction, Profile, Paper } from '../dockshiftApi';
import type { CollectiveOutput } from './CollectiveWorkflow';

export interface ManagedRunResult extends AgentRunResult {
  outputs?: ResearchOutputs;
  workflow?: string;
  candidate_screening_status?: string;
  review_provider?: string | null;
}
export interface ManagedCapabilities extends AgentCapabilities {
  admet_enabled?: boolean;
  llm?: { available: boolean; model: string | null; detail: string | null };
}
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
  return body;
}
export const fetchResearchCapabilities = () => call<ManagedCapabilities>('/api/v1/agents/capabilities');
export const fetchResearchReport = (id: string, token: string) =>
  call<ManagedRunResult>(`/api/v1/agents/runs/${encodeURIComponent(id)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

export interface ResearchProgress {
  run_id: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'BLOCKED' | 'FAILED';
  detail?: string;
  agents: Array<{ agent: string; role: string; scientific_status: string; detail: string }>;
}
export interface ScientificArtifact {
  filename: string; sha256: string; size_bytes: number; hash_verified: boolean;
  data: unknown;
}
export interface ResearchOutputs {
  collective?: CollectiveOutput;
  target?: Record<string, unknown>;
  screening?: { qsar: { predictions: Prediction[] }; profiles: { profiles: Profile[] };
    chemical_audit: Record<string, unknown>; model: unknown; versions: Record<string, string> };
  admet?: { model_version?: string; endpoints?: Array<{ endpoint: string; value: number; units: string; species: string; task_type: string }>; validation: string; artifacts: ScientificArtifact[]; limitations: string[] };
  admet_operation?: { status: string; operation_id?: string };
  literature?: { results: Paper[]; errors: Array<{ source: string; message: string }>; retrieval_status: string };
  docking?: unknown;
}
export const preflightResearch = (request: unknown, token: string) =>
  call<unknown>('/api/v1/agents/preflight', {
    method: 'POST', headers: { 'content-type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(request),
  });
export const startResearch = (request: unknown, token: string) =>
  call<{ run_id: string; status: string }>('/api/v1/agents/research', {
    method: 'POST', headers: { 'content-type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(request),
  });
export const fetchResearchProgress = (id: string, token: string) =>
  call<ResearchProgress>(`/api/v1/agents/runs/${encodeURIComponent(id)}/progress`, {
    headers: { Authorization: `Bearer ${token}` },
  });
export const resumeResearch = (id: string, token: string) =>
  call<{ run_id: string; status: string }>(`/api/v1/agents/runs/${encodeURIComponent(id)}/resume`, {
    method: 'POST', headers: { Authorization: `Bearer ${token}` },
  });
export async function downloadResearchArtifact(id: string, name: string, token: string) {
  const response = await fetch(`${API_BASE}/api/v1/agents/runs/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(name)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`Artifact retrieval failed: HTTP ${response.status}`);
  return response.blob();
}
