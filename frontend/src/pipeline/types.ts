/**
 * The discovery pipeline, as a run of ordered stages.
 *
 * Every number a stage reports carries its own provenance, so the interface can
 * never present a model estimate as a measurement. `origin` is the whole point:
 *
 *   measured   experimental value from ChEMBL
 *   predicted  QSAR model output, ~0.5 log unit error
 *   computed   produced by an external engine this run (DiffDock, AlphaFold)
 *   derived    arithmetic on the above, nothing new
 *   reference  from a stored result set, not produced by an engine this run
 *   pending    the stage has not produced it yet
 */

export type StageId =
  | 'target'
  | 'candidates'
  | 'selection'
  | 'structure'
  | 'docking'
  | 'dynamics'
  | 'iterate';

export type StageState =
  | 'idle'
  | 'running'
  | 'complete'
  | 'failed'
  | 'blocked'
  | 'skipped';

export type Origin =
  | 'measured'
  | 'predicted'
  | 'computed'
  | 'derived'
  | 'reference'
  | 'pending';

export interface Metric {
  label: string;
  value: string;
  origin: Origin;
  hint?: string;
}

/** One line in the run ledger. The audit trail, not decoration. */
export interface LedgerEntry {
  at: number;
  stage: StageId;
  level: 'info' | 'warn' | 'error';
  message: string;
  /** Remote operation id, when an external engine was called. */
  ref?: string;
  /** Milliseconds, when the step finished. */
  elapsedMs?: number;
}

export interface StageRun {
  id: StageId;
  title: string;
  /** One line: what this stage does. No encouragement, no exclamation marks. */
  summary: string;
  engine: string;
  state: StageState;
  startedAt?: number;
  endedAt?: number;
  progress?: number;
  detail?: string;
  metrics: Metric[];
  /** Why the stage cannot run, when state is 'blocked'. */
  blockedReason?: string;
}

export interface CandidateRow {
  rank: number;
  name: string;
  smiles?: string;
  note?: string;
  predictedPic50?: number | null;
  predictedIc50Nm?: number | null;
  measuredPic50?: number | null;
  maxTanimoto?: number | null;
  domain?: 'in' | 'out' | null;
  inTrainingSet?: boolean;
  qed?: number | null;
  lipinskiViolations?: number | null;
  veberPass?: boolean | null;
  molecularWeight?: number | null;
  clogp?: number | null;
  selected: boolean;
  /** Set when this row came out of the iterate stage rather than the shortlist. */
  derivedFrom?: string;
  dockingConfidence?: number | null;
  dockingSite?: string;
  dockingOperationId?: string;
}

export interface RunState {
  runId: string;
  startedAt: number;
  target: { id: string; name: string; chemblId?: string; receptor: string };
  stages: Record<StageId, StageRun>;
  candidates: CandidateRow[];
  ledger: LedgerEntry[];
  activeStage: StageId;
  cycle: number;
}

export const STAGE_ORDER: StageId[] = [
  'target',
  'candidates',
  'selection',
  'structure',
  'docking',
  'dynamics',
  'iterate',
];
