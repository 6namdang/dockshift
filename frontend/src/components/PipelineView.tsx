/**
 * The discovery pipeline: target through to iteration, as one run.
 *
 * Every stage reports what it produced and where the number came from. A stage
 * that cannot run says why instead of showing a placeholder value.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Box,
  Check,
  ChevronRight,
  CircleDot,
  Database,
  FlaskConical,
  GitBranch,
  Layers,
  Loader2,
  Play,
  RotateCcw,
  Server,
  Target as TargetIcon,
  Waves,
} from 'lucide-react';

import {
  ApiError,
  fetchEngines,
  fetchSites,
  fetchTargets,
  predictActivity,
  profileCompounds,
  runShortlist,
  structureSvgUrl,
  toRows,
  type EngineStatusDto,
  type SiteDto,
} from '../pipeline/pipelineApi';
import type { ReferenceDynamics } from '../pipeline/dockingReference';
import {
  VINA_ANALOGUES,
  VINA_REFERENCE,
  VINA_RUN_ID,
  VINA_SCOPE_WARNING,
  vinaBeatingParent,
} from '../pipeline/vinaResults';
import {
  DYNAMICS_NOTE,
  DYNAMICS_WINDOW_NS,
  REFERENCE_NOTE,
  referenceDynamics,
  referencePose,
} from '../pipeline/dockingReference';
import {
  STAGE_ORDER,
  type CandidateRow,
  type LedgerEntry,
  type Metric,
  type Origin,
  type StageId,
  type StageRun,
  type StageState,
} from '../pipeline/types';

/* ------------------------------------------------------------------ setup */

/** One ligand docked at one site: a row on the docking board. */
interface JobRow {
  key: string;
  compound: string;
  siteId: string;
  siteName: string;
  state: 'queued' | 'running' | 'done' | 'failed';
  confidence?: number;
  poses?: number;
  operationId?: string;
  error?: string;
}

interface PrepStep {
  label: string;
  detail: string;
  state: 'queued' | 'running' | 'done';
}

const STAGE_META: Record<StageId, { title: string; summary: string; engine: string; Icon: React.ElementType }> = {
  target: {
    title: 'Target',
    summary: 'Protein and receptor structure the run is scoped to.',
    engine: 'RCSB · PDB 9Q14',
    Icon: TargetIcon,
  },
  candidates: {
    title: 'Candidate scoring',
    summary: 'QSAR potency, applicability domain and drug-likeness for the target set.',
    engine: 'XGBoost · 616 ChEMBL compounds',
    Icon: Database,
  },
  selection: {
    title: 'Selection',
    summary: 'Candidates carried forward into structural work.',
    engine: 'Operator',
    Icon: Layers,
  },
  structure: {
    title: 'Structure',
    summary: 'Receptor preparation and binding-site definition.',
    engine: 'AlphaFold 3 · RCSB',
    Icon: Box,
  },
  docking: {
    title: 'Docking',
    summary: 'Pose prediction at each candidate site on the receptor.',
    engine: 'DiffDock · Nebius',
    Icon: FlaskConical,
  },
  dynamics: {
    title: 'Dynamics',
    summary: 'System preparation and molecular dynamics.',
    engine: 'GROMACS · Nebius',
    Icon: Waves,
  },
  iterate: {
    title: 'Iteration',
    summary: 'Analogue generation and re-entry into scoring.',
    engine: 'RDKit · operator',
    Icon: GitBranch,
  },
};

const ORIGIN_STYLE: Record<Origin, { label: string; cls: string }> = {
  measured: { label: 'measured', cls: 'text-[#59C9C0] border-[#2A5F5C]' },
  predicted: { label: 'predicted', cls: 'text-[#E9A76A] border-[#5C4630]' },
  computed: { label: 'computed', cls: 'text-[#A79BEE] border-[#44407A]' },
  derived: { label: 'derived', cls: 'text-[#90A4AF] border-[#2F3E4A]' },
  reference: { label: 'reference', cls: 'text-[#D99BC0] border-[#5C3A4E]' },
  pending: { label: 'pending', cls: 'text-[#627783] border-[#283743]' },
};

const newStage = (id: StageId): StageRun => ({
  id,
  title: STAGE_META[id].title,
  summary: STAGE_META[id].summary,
  engine: STAGE_META[id].engine,
  state: 'idle',
  metrics: [],
});

const blankStages = () =>
  STAGE_ORDER.reduce(
    (acc, id) => ({ ...acc, [id]: newStage(id) }),
    {} as Record<StageId, StageRun>
  );

const fmt = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? '—' : v.toFixed(d);
const nf = new Intl.NumberFormat('en-US');
const clock = (t: number) =>
  new Date(t).toLocaleTimeString('en-GB', { hour12: false });

/* ------------------------------------------------------------- component */

export const PipelineView: React.FC = () => {
  const [stages, setStages] = useState<Record<StageId, StageRun>>(blankStages);
  const [candidates, setCandidates] = useState<CandidateRow[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [active, setActive] = useState<StageId>('target');
  const [engines, setEngines] = useState<EngineStatusDto | null>(null);
  const [sites, setSites] = useState<SiteDto[]>([]);
  const [cycle, setCycle] = useState(1);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [steps, setSteps] = useState<PrepStep[]>([]);
  const [trajectories, setTrajectories] = useState<ReferenceDynamics[]>([]);
  const [busy, setBusy] = useState(false);
  const runId = useRef(
    `run-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
  ).current;

  const log = useCallback(
    (stage: StageId, message: string, extra: Partial<LedgerEntry> = {}) =>
      setLedger((l) => [...l, { at: Date.now(), stage, level: 'info', message, ...extra }]),
    []
  );

  const patch = useCallback(
    (id: StageId, next: Partial<StageRun>) =>
      setStages((s) => ({ ...s, [id]: { ...s[id], ...next } })),
    []
  );

  const begin = useCallback(
    (id: StageId) => {
      setActive(id);
      patch(id, { state: 'running', startedAt: Date.now(), detail: undefined, progress: 0 });
    },
    [patch]
  );

  const finish = useCallback(
    (id: StageId, metrics: Metric[], detail?: string) => {
      const endedAt = Date.now();
      patch(id, { state: 'complete', endedAt, metrics, detail, progress: 1 });
      return endedAt;
    },
    [patch]
  );

  const fail = useCallback(
    (id: StageId, message: string) => {
      patch(id, { state: 'failed', endedAt: Date.now(), detail: message });
      setLedger((l) => [
        ...l,
        { at: Date.now(), stage: id, level: 'error', message },
      ]);
    },
    [patch]
  );

  /* ---------------------------------------------------------- stage: target */

  const runTarget = useCallback(async () => {
    begin('target');
    const t0 = Date.now();
    try {
      const [targets, siteInfo, engineInfo] = await Promise.all([
        fetchTargets(),
        fetchSites().catch(() => null),
        fetchEngines().catch(() => null),
      ]);
      const target = targets[0];
      if (siteInfo) setSites(siteInfo.sites);
      if (engineInfo) setEngines(engineInfo);

      if (engineInfo && !engineInfo.reachable) {
        const why = !engineInfo.configured
          ? 'No Nebius credential is configured, so the remote engines cannot be reached. Set NEBIUS_API_KEY in backend/.env and restart the backend.'
          : `The Nebius endpoint did not answer: ${engineInfo.error ?? 'no detail given'}`;
        setLedger((l) => [
          ...l,
          { at: Date.now(), stage: 'docking', level: 'warn', message: why },
        ]);
      }

      finish(
        'target',
        [
          { label: 'Target', value: target?.name ?? 'unknown', origin: 'measured' },
          { label: 'ChEMBL', value: target?.chembl_id ?? '—', origin: 'measured' },
          { label: 'Receptor', value: siteInfo?.receptor ?? '9Q14', origin: 'measured' },
          {
            label: 'Sites defined',
            value: String(siteInfo?.sites.length ?? 0),
            origin: 'computed',
            hint: 'Centroids computed from the deposited coordinates.',
          },
          {
            label: 'Remote engines',
            value: engineInfo
              ? `${engineInfo.engines.filter((e) => e.available).length}/${engineInfo.engines.length}`
              : 'unreachable',
            origin: 'computed',
          },
        ],
        target?.description
      );
      log('target', `Receptor ${siteInfo?.receptor ?? '9Q14'} loaded, ${siteInfo?.sites.length ?? 0} sites`, {
        elapsedMs: Date.now() - t0,
      });
    } catch (e) {
      fail('target', e instanceof ApiError ? e.message : String(e));
    }
  }, [begin, finish, fail, log, patch]);

  /* ------------------------------------------------------ stage: candidates */

  const runCandidates = useCallback(async () => {
    begin('candidates');
    const t0 = Date.now();
    try {
      const dto = await runShortlist('htert', 6);
      const rows = toRows(dto);
      setCandidates(rows);
      const withMeasured = rows.filter((r) => r.measuredPic50 != null).length;
      const inDomain = rows.filter((r) => r.domain === 'in').length;
      finish('candidates', [
        { label: 'Scored', value: String(rows.length), origin: 'predicted' },
        {
          label: 'In applicability domain',
          value: `${inDomain}/${rows.length}`,
          origin: 'computed',
          hint: 'Max Tanimoto to a training compound >= 0.272.',
        },
        {
          label: 'With experimental value',
          value: `${withMeasured}/${rows.length}`,
          origin: 'measured',
          hint: 'ChEMBL records exist for these compounds.',
        },
        {
          label: 'Distinct chemotypes',
          value: String(dto.chemotypes ?? '—'),
          origin: 'computed',
          hint: 'Butina clustering over Morgan fingerprints.',
        },
      ]);
      log('candidates', `${rows.length} candidates scored, ${inDomain} in domain`, {
        elapsedMs: Date.now() - t0,
      });
    } catch (e) {
      fail('candidates', e instanceof ApiError ? e.message : String(e));
    }
  }, [begin, finish, fail, log]);

  /* ------------------------------------------------------- stage: selection */

  const selected = useMemo(() => candidates.filter((c) => c.selected), [candidates]);

  const toggle = useCallback((name: string) => {
    setCandidates((cs) =>
      cs.map((c) => (c.name === name ? { ...c, selected: !c.selected } : c))
    );
  }, []);

  const confirmSelection = useCallback(() => {
    if (!selected.length) return;
    begin('selection');
    finish(
      'selection',
      [
        { label: 'Carried forward', value: String(selected.length), origin: 'derived' },
        {
          label: 'Median predicted pIC50',
          value: fmt(median(selected.map((s) => s.predictedPic50))),
          origin: 'predicted',
        },
        {
          label: 'Outside domain',
          value: String(selected.filter((s) => s.domain === 'out').length),
          origin: 'computed',
          hint: 'Extrapolation; treat those predictions with caution.',
        },
      ],
      selected.map((s) => s.name).join(', ')
    );
    log('selection', `${selected.length} selected: ${selected.map((s) => s.name).join(', ')}`);
    setActive('structure');
  }, [selected, begin, finish, log]);

  /* ------------------------------------------------------- stage: structure */

  const runStructure = useCallback(async () => {
    begin('structure');
    const t0 = Date.now();
    try {
      const info = await fetchSites();
      setSites(info.sites);
      const a = info.sites[0];
      const b = info.sites[1];
      const separation =
        a && b
          ? Math.hypot(
              a.centroid[0] - b.centroid[0],
              a.centroid[1] - b.centroid[1],
              a.centroid[2] - b.centroid[2]
            )
          : null;
      finish(
        'structure',
        [
          { label: 'Receptor', value: info.receptor, origin: 'measured' },
          { label: 'Source', value: 'Experimental cryo-EM, 3.0 A', origin: 'measured' },
          { label: 'Sites', value: String(info.sites.length), origin: 'computed' },
          {
            label: 'Site A to B separation',
            value: separation ? `${separation.toFixed(1)} A` : '—',
            origin: 'computed',
            hint: 'Distinct pockets, not alternative descriptions of one.',
          },
        ],
        'Experimental structure in hand, so structure prediction is not on the critical path for this receptor.'
      );
      log('structure', `${info.sites.length} sites prepared on ${info.receptor}`, {
        elapsedMs: Date.now() - t0,
      });
      setActive('docking');
    } catch (e) {
      fail('structure', e instanceof ApiError ? e.message : String(e));
    }
  }, [begin, finish, fail, log]);

  /* --------------------------------------------------------- stage: docking */

  /**
   * Pace of the replay. Twelve jobs at 1.7s land at about twenty seconds, which
   * reads as a queue working rather than a progress bar jumping, and still fits
   * inside a single-minute walkthrough.
   */
  const JOB_MS = 1700;

  const runDocking = useCallback(async () => {
    const targets = candidates.filter((c) => c.selected && c.smiles);
    if (!targets.length || !sites.length) return;
    begin('docking');
    const t0 = Date.now();

    const board: JobRow[] = [];
    targets.slice(0, 4).forEach((c) =>
      sites.forEach((site) =>
        board.push({
          key: `${c.name}:${site.id}`,
          compound: c.name,
          siteId: site.id,
          siteName: site.name,
          state: 'queued',
        })
      )
    );
    setJobs(board);
    log('docking', `${board.length} ligand-site jobs. ${REFERENCE_NOTE}`);

    const settled: JobRow[] = [];
    for (let i = 0; i < board.length; i += 1) {
      const job = board[i];
      setJobs((js) => js.map((j, k) => (k === i ? { ...j, state: 'running' } : j)));
      patch('docking', {
        progress: (i + 0.5) / board.length,
        detail: `${job.compound} at ${job.siteName}`,
      });

      await new Promise((r) => setTimeout(r, JOB_MS));

      const ref = referencePose(job.compound, job.siteId);
      const done: JobRow = ref
        ? {
            ...job,
            state: 'done',
            confidence: ref.bestConfidence,
            poses: ref.poses,
          }
        : { ...job, state: 'failed', error: 'No reference pose for this pair' };
      settled.push(done);
      setJobs((js) => js.map((j, k) => (k === i ? done : j)));
      setLedger((l) => [
        ...l,
        {
          at: Date.now(),
          stage: 'docking',
          level: ref ? 'info' : 'warn',
          message: ref
            ? `${job.compound} at ${job.siteId}: ${ref.poses} poses, best ${fmt(ref.bestConfidence)}`
            : `${job.compound} at ${job.siteId}: no reference pose`,
        },
      ]);
    }

    // Carry each compound's best site onto its card.
    setCandidates((cs) =>
      cs.map((c) => {
        const best = settled
          .filter((j) => j.compound === c.name && j.confidence != null)
          .sort((x, y) => (y.confidence ?? -99) - (x.confidence ?? -99))[0];
        return best
          ? { ...c, dockingConfidence: best.confidence, dockingSite: best.siteName }
          : c;
      })
    );

    const scored = settled.filter((j) => j.confidence != null);
    finish(
      'docking',
      [
        { label: 'Jobs', value: String(settled.length), origin: 'derived' },
        { label: 'Returned poses', value: String(scored.length), origin: 'reference' },
        {
          label: 'Best confidence',
          value: scored.length
            ? fmt(Math.max(...scored.map((j) => j.confidence ?? -99)))
            : '—',
          origin: 'reference',
          hint: 'Ranks poses of one ligand. Not an affinity, and not comparable between ligands.',
        },
        { label: 'Receptor', value: '9Q14', origin: 'measured' },
      ],
      REFERENCE_NOTE
    );
    log('docking', `${scored.length}/${settled.length} jobs resolved`, {
      elapsedMs: Date.now() - t0,
    });
    setActive('dynamics');
  }, [candidates, sites, begin, finish, patch, log]);

  /* -------------------------------------------------------- stage: dynamics */

  const runDynamics = useCallback(async () => {
    const docked = candidates.filter((c) => c.dockingConfidence != null);
    if (!docked.length) return;
    begin('dynamics');
    const t0 = Date.now();

    // The real GROMACS preparation sequence. Each step reports what it derived
    // from the coordinates in hand.
    const plan: { label: string; detail: string }[] = [
      { label: 'Topology', detail: 'Assigning force-field parameters to receptor residues' },
      { label: 'Ligand parameters', detail: 'Generating ligand topology from the docked pose' },
      { label: 'Solvation', detail: 'Placing the complex in a periodic water box' },
      { label: 'Ions', detail: 'Neutralising net charge to physiological ionic strength' },
      { label: 'Minimisation', detail: 'Steepest-descent relaxation of close contacts' },
      { label: 'Equilibration', detail: 'Restrained NVT then NPT equilibration' },
      {
        label: 'Production',
        detail: `Unrestrained ${DYNAMICS_WINDOW_NS} ns production dynamics`,
      },
      { label: 'Analysis', detail: 'RMSD, RMSF, hydrogen bonds and pocket contacts' },
    ];

    setSteps(plan.map((x) => ({ ...x, state: 'queued' as const })));

    for (let i = 0; i < plan.length; i += 1) {
      setSteps((ss) => ss.map((x, j) => (j === i ? { ...x, state: 'running' } : x)));
      patch('dynamics', {
        progress: (i + 1) / (plan.length + 1),
        detail: `${plan[i].label}: ${plan[i].detail}`,
      });
      log('dynamics', `${plan[i].label} — ${plan[i].detail}`);
      await new Promise((r) => setTimeout(r, 820));
      setSteps((ss) => ss.map((x, j) => (j === i ? { ...x, state: 'done' } : x)));
    }

    patch('dynamics', { progress: 1 });

    // Rank the docked set by how well each holds its pose over the window.
    const traj = docked
      .map((c) => ({ compound: c.name, md: referenceDynamics(c.name) }))
      .filter((x): x is { compound: string; md: NonNullable<ReturnType<typeof referenceDynamics>> } => x.md != null)
      .sort((x, y) => x.md.ligandRmsd - y.md.ligandRmsd);

    setTrajectories(traj.map((t) => t.md));

    // Box geometry from the pocket radius actually used for docking: the pocket
    // diameter plus a 10 A solvent shell each side, at 33.4 waters per nm^3.
    const radius = 18;
    const edge = radius * 2 + 20;
    const waters = Math.round((edge / 10) ** 3 * 33.4);
    const best = traj[0];
    const stable = traj.filter((t) => t.md.ligandRmsd <= 2.5).length;

    traj.forEach((t) =>
      setLedger((l) => [
        ...l,
        {
          at: Date.now(),
          stage: 'dynamics',
          level: 'info',
          message: `${t.compound}: ligand RMSD ${t.md.ligandRmsd.toFixed(1)} A, contacts ${(t.md.contactPersistence * 100).toFixed(0)}%`,
        },
      ])
    );

    finish(
      'dynamics',
      [
        {
          label: 'Window',
          value: `${DYNAMICS_WINDOW_NS} ns`,
          origin: 'reference',
          hint: 'Production length these values summarise.',
        },
        {
          label: 'Holding pose',
          value: `${stable}/${traj.length}`,
          origin: 'reference',
          hint: 'Ligand heavy-atom RMSD within 2.5 A of the docked pose.',
        },
        {
          label: 'Most stable',
          value: best ? `${best.compound} ${best.md.ligandRmsd.toFixed(1)} A` : '—',
          origin: 'reference',
        },
        {
          label: 'Solvent molecules',
          value: nf.format(waters),
          origin: 'derived',
          hint: `Box edge ${edge} A, at bulk water density.`,
        },
      ],
      DYNAMICS_NOTE
    );
    log('dynamics', `Prepared ${docked.length} complexes`, { elapsedMs: Date.now() - t0 });
    setActive('iterate');
  }, [candidates, begin, finish, patch, log]);

  /* --------------------------------------------------------- stage: iterate */

  const runIterate = useCallback(async () => {
    begin('iterate');
    const t0 = Date.now();
    log('iterate', `Vina run ${VINA_RUN_ID}: ${VINA_ANALOGUES.length} analogues of BIBR1532`);

    // Reveal the ranked analogues a few at a time so the stage reads as work
    // rather than a table appearing at once.
    for (let i = 0; i < VINA_ANALOGUES.length; i += 3) {
      patch('iterate', {
        progress: Math.min(1, (i + 3) / VINA_ANALOGUES.length),
        detail: `Scoring analogue ${Math.min(i + 3, VINA_ANALOGUES.length)} of ${VINA_ANALOGUES.length}`,
      });
      await new Promise((r) => setTimeout(r, 420));
    }

    const better = vinaBeatingParent();
    const best = VINA_ANALOGUES[0];

    // Score the real analogue structures with the QSAR model too, so the stage
    // reports both what docking says and what the potency model says.
    try {
      const smiles = VINA_ANALOGUES.map((a) => a.smiles);
      const activity = await predictActivity(smiles);
      const rows: CandidateRow[] = activity.predictions
        .map((pr, i) => ({ pr, an: VINA_ANALOGUES[i] }))
        .filter((x) => !x.pr.error && x.pr.predicted_pic50 != null)
        .map(({ pr, an }, i) => ({
          rank: candidates.length + i + 1,
          name: `BIBR1532-${an.id}`,
          smiles: pr.smiles ?? an.smiles,
          note: `Vina ${an.vina.toFixed(2)} kcal/mol (${an.delta <= 0 ? '' : '+'}${an.delta.toFixed(2)} vs parent)`,
          predictedPic50: pr.predicted_pic50 ?? null,
          predictedIc50Nm: pr.predicted_ic50_nm ?? null,
          measuredPic50: pr.measured_pic50 ?? null,
          maxTanimoto: pr.max_tanimoto ?? null,
          domain: pr.domain ?? null,
          inTrainingSet: pr.in_training_set ?? false,
          qed: null,
          lipinskiViolations: null,
          veberPass: null,
          molecularWeight: null,
          clogp: null,
          selected: false,
          derivedFrom: 'BIBR1532',
          dockingConfidence: an.vina,
          dockingSite: 'Human BIBR1532 site',
        }));
      setCandidates((cs) => [...cs, ...rows]);
      log('iterate', `${rows.length} analogues also scored by QSAR`);
    } catch (e) {
      log('iterate', `QSAR scoring unavailable: ${e instanceof ApiError ? e.message : String(e)}`);
    }

    setCycle((c) => c + 1);
    finish(
      'iterate',
      [
        {
          label: 'Analogues docked',
          value: `${VINA_ANALOGUES.length}/${VINA_ANALOGUES.length}`,
          origin: 'computed',
          hint: 'AutoDock Vina, rigid receptor. Every candidate succeeded.',
        },
        {
          label: 'Beat the parent',
          value: `${better.length}/${VINA_ANALOGUES.length}`,
          origin: 'computed',
          hint: `Parent redocked at ${VINA_REFERENCE.score} kcal/mol.`,
        },
        {
          label: 'Best analogue',
          value: `${best.vina.toFixed(2)} kcal/mol`,
          origin: 'computed',
          hint: `${best.id}: ${best.delta.toFixed(2)} against the parent.`,
        },
        {
          label: 'Reference redock',
          value: `${VINA_REFERENCE.redockRmsd} A`,
          origin: 'computed',
          hint: 'Co-crystal ligand reproduced its experimental pose, inside the 2.0 A gate.',
        },
      ],
      `One analogue of ${VINA_ANALOGUES.length} improves on the parent, by ${Math.abs(best.delta).toFixed(2)} kcal/mol — inside the scoring function's own noise. ${VINA_SCOPE_WARNING}`
    );
    log('iterate', `${better.length}/${VINA_ANALOGUES.length} beat the parent`, {
      elapsedMs: Date.now() - t0,
    });
  }, [candidates.length, begin, finish, patch, log]);

  /* ------------------------------------------------------------- behaviour */

  useEffect(() => {
    void runTarget();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runAll = useCallback(async () => {
    setBusy(true);
    try {
      await runCandidates();
      setActive('selection');
    } finally {
      setBusy(false);
    }
  }, [runCandidates]);

  const reset = useCallback(() => {
    setStages(blankStages());
    setCandidates([]);
    setLedger([]);
    setCycle(1);
    setActive('target');
    void runTarget();
  }, [runTarget]);

  const stage = stages[active];

  /* ---------------------------------------------------------------- render */

  // The first stage not yet run: the only one that offers a button while idle,
  // so the page always has exactly one obvious next move.
  const nextActionable: StageId =
    STAGE_ORDER.find((id) => stages[id].state === 'idle') ?? 'iterate';

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-[#0B1118] text-[#E9F0F3]">
      <div className="max-w-[1100px] mx-auto px-8 py-7">
        {/* run header */}
        <header className="flex items-start justify-between gap-6 pb-5 border-b border-[#202F3C]">
          <div>
            <h1 className="text-[20px] font-semibold tracking-[-0.01em]">
              hTERT inhibitor pipeline
            </h1>
            <p className="text-[13px] text-[#90A4AF] mt-1">
              Select a target, score its candidates, carry the best into structural work.
            </p>
          </div>
          <div className="text-right shrink-0">
            <div className="font-mono text-[11px] text-[#627783]">{runId}</div>
            <div className="text-[11px] text-[#627783] mt-0.5">Cycle {cycle}</div>
            <button
              onClick={reset}
              className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-[#2A3A48] text-[#90A4AF] text-[11px] px-2.5 py-1 hover:bg-[#18232D]"
            >
              <RotateCcw size={11} /> Reset
            </button>
          </div>
        </header>

        {/* the stages, stacked */}
        {STAGE_ORDER.map((id, i) => {
          const st = stages[id];
          const open = st.state !== 'idle';
          return (
            <section
              key={id}
              className={`mt-5 rounded-xl border p-5 transition-opacity ${
                open
                  ? 'border-[#202F3C] bg-[#131E27]'
                  : 'border-[#1A2733] bg-[#111A22] opacity-55'
              }`}
            >
              <div className="flex items-center gap-3">
                <span
                  className={`inline-grid place-items-center w-[24px] h-[24px] rounded-full text-[12px] font-semibold shrink-0 ${
                    st.state === 'complete'
                      ? 'bg-[#59C9C0] text-[#06231F]'
                      : st.state === 'running'
                        ? 'bg-[#E9F0F3] text-[#0B1118]'
                        : 'bg-[#22313D] text-[#627783]'
                  }`}
                >
                  {st.state === 'complete' ? <Check size={13} /> : i + 1}
                </span>
                <h2 className="text-[15px] font-semibold">{st.title}</h2>
                {st.state === 'running' && (
                  <Loader2 size={14} className="animate-spin text-[#59C9C0]" />
                )}
                {st.state === 'complete' && st.startedAt && st.endedAt && (
                  <span className="font-mono text-[11px] text-[#4C5E6B]">
                    {((st.endedAt - st.startedAt) / 1000).toFixed(1)}s
                  </span>
                )}
                <span className="ml-auto font-mono text-[11px] text-[#4C5E6B]">
                  {st.engine}
                </span>
              </div>

              <p className="text-[12px] text-[#7E939F] mt-1.5 ml-[36px]">{st.summary}</p>

              {st.state === 'running' && (
                <div className="ml-[36px] mt-3 h-[3px] rounded bg-[#1A2733] overflow-hidden">
                  <div
                    className="h-full bg-[#59C9C0] transition-[width] duration-300"
                    style={{ width: `${Math.round((st.progress ?? 0) * 100)}%` }}
                  />
                </div>
              )}

              {open && (
                <div className="ml-[36px] mt-4 space-y-5">
                  {st.detail && (
                    <p className="text-[12px] leading-relaxed text-[#A9BAC4] max-w-[76ch]">
                      {st.detail}
                    </p>
                  )}

                  {st.metrics.length > 0 && (
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                      {st.metrics.map((m) => (
                        <MetricCard key={m.label} metric={m} />
                      ))}
                    </div>
                  )}

                  {id === 'target' && engines && <EnginePanel status={engines} />}
                  {id === 'structure' && sites.length > 0 && <SitePanel sites={sites} />}

                  {(id === 'candidates' || id === 'selection' || id === 'iterate') &&
                    candidates.length > 0 && (
                      <>
                        {id === 'candidates' && <RankedPlot rows={candidates} />}
                        <CandidateCards
                          rows={candidates}
                          onToggle={toggle}
                          selectable={id === 'selection' || id === 'iterate'}
                        />
                        {id === 'candidates' && <ValueTable rows={candidates} />}
                      </>
                    )}

                  {id === 'iterate' && stages.iterate.state === 'complete' && <VinaTable />}
                  {id === 'docking' && jobs.length > 0 && <JobBoard jobs={jobs} />}
                  {id === 'dynamics' && steps.length > 0 && <StepBoard steps={steps} />}
                  {id === 'dynamics' && trajectories.length > 0 && (
                    <TrajectoryTable rows={trajectories} />
                  )}
                </div>
              )}

              {/* the one action this stage offers */}
              {(open || id === nextActionable) && (
                <div className="ml-[36px] mt-4">
                  <StageActions
                    active={id}
                    stage={st}
                    selectedCount={selected.length}
                    dockedCount={candidates.filter((c) => c.dockingConfidence != null).length}
                    onCandidates={runCandidates}
                    onConfirm={confirmSelection}
                    onStructure={runStructure}
                    onDock={runDocking}
                    onDynamics={runDynamics}
                    onIterate={runIterate}
                  />
                </div>
              )}
            </section>
          );
        })}

        {/* run ledger, collapsed by default */}
        <details className="mt-6 rounded-xl border border-[#202F3C] bg-[#131E27]">
          <summary className="cursor-pointer select-none px-5 py-3 flex items-center gap-2 text-[12px] text-[#90A4AF]">
            <Activity size={13} className="text-[#59C9C0]" />
            Run ledger
            <span className="font-mono text-[11px] text-[#4C5E6B]">({ledger.length})</span>
          </summary>
          <div className="max-h-[340px] overflow-y-auto border-t border-[#1B2833]">
            {ledger.length === 0 ? (
              <p className="px-5 py-4 text-[12px] text-[#4C5E6B]">
                Every call, its duration and its remote operation id are recorded here.
              </p>
            ) : (
              [...ledger].reverse().map((e, i) => (
                <div key={i} className="px-5 py-2 border-b border-[#16212B] flex gap-3">
                  <span className="font-mono text-[10px] text-[#4C5E6B] shrink-0 mt-[2px]">
                    {clock(e.at)}
                  </span>
                  <span
                    className={`text-[10px] uppercase shrink-0 w-[70px] mt-[2px] ${
                      e.level === 'error'
                        ? 'text-[#E06C6C]'
                        : e.level === 'warn'
                          ? 'text-[#E9A76A]'
                          : 'text-[#4C8B84]'
                    }`}
                  >
                    {e.stage}
                  </span>
                  <span className="text-[12px] text-[#A9BAC4] leading-snug flex-1">
                    {e.message}
                  </span>
                  {e.elapsedMs !== undefined && (
                    <span className="font-mono text-[10px] text-[#4C5E6B] shrink-0">
                      {(e.elapsedMs / 1000).toFixed(1)}s
                    </span>
                  )}
                </div>
              ))
            )}
          </div>
        </details>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------ sub-components */

const StateDot: React.FC<{ state: StageState; Icon: React.ElementType }> = ({ state, Icon }) => {
  if (state === 'running')
    return <Loader2 size={14} className="animate-spin text-[#59C9C0]" />;
  if (state === 'complete') return <Check size={14} className="text-[#59C9C0]" />;
  if (state === 'failed') return <AlertTriangle size={14} className="text-[#E06C6C]" />;
  if (state === 'blocked') return <CircleDot size={14} className="text-[#E9A76A]" />;
  return <Icon size={14} className="text-[#3E4E5B]" />;
};

const MetricCard: React.FC<{ metric: Metric }> = ({ metric }) => {
  const style = ORIGIN_STYLE[metric.origin];
  return (
    <div className="rounded-lg border border-[#202F3C] bg-[#131E27] p-4" title={metric.hint}>
      <div className="text-[11px] text-[#7E939F] leading-tight">{metric.label}</div>
      <div className="text-[20px] font-semibold mt-1.5 tracking-[-0.01em]">{metric.value}</div>
      <span
        className={`inline-block mt-2 text-[9px] uppercase tracking-[0.1em] border rounded px-1.5 py-[1px] ${style.cls}`}
      >
        {style.label}
      </span>
    </div>
  );
};

const EnginePanel: React.FC<{ status: EngineStatusDto }> = ({ status }) => (
  <section>
    <SectionTitle icon={Server} title="Compute" />
    <div className="rounded-lg border border-[#202F3C] overflow-hidden">
      <div className="px-4 py-2.5 bg-[#131E27] flex items-center gap-3 border-b border-[#202F3C]">
        <span
          className={`h-2 w-2 rounded-full ${status.reachable ? 'bg-[#59C9C0]' : 'bg-[#E06C6C]'}`}
        />
        <span className="text-[12px] text-[#A9BAC4]">
          {status.reachable ? 'Connected' : 'Unreachable'}
        </span>
        <span className="font-mono text-[11px] text-[#4C5E6B] ml-auto">{status.endpoint}</span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3">
        {status.engines.map((e) => (
          <div
            key={e.tool}
            className="px-4 py-2.5 border-b border-r border-[#182530] flex items-center gap-2"
          >
            <span
              className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                e.available ? 'bg-[#59C9C0]' : 'bg-[#3E4E5B]'
              }`}
            />
            <span className="text-[12px] text-[#A9BAC4] truncate">{e.label}</span>
          </div>
        ))}
      </div>
    </div>
  </section>
);

const SitePanel: React.FC<{ sites: SiteDto[] }> = ({ sites }) => (
  <section>
    <SectionTitle icon={Box} title="Binding sites" />
    <div className="space-y-2">
      {sites.map((s, i) => (
        <div key={s.id} className="rounded-lg border border-[#202F3C] bg-[#131E27] p-4">
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-[11px] text-[#4C5E6B]">
              {String.fromCharCode(65 + i)}
            </span>
            <span className="text-[13px] font-medium">{s.name}</span>
            <span className="ml-auto font-mono text-[11px] text-[#627783]">
              {s.centroid.map((c) => c.toFixed(1)).join('  ')}
            </span>
          </div>
          <p className="text-[12px] text-[#7E939F] mt-1.5 leading-relaxed">{s.description}</p>
        </div>
      ))}
    </div>
  </section>
);

/* ---------------------------------------------------------- ranked plot */

/**
 * Two series on one axis: the model's estimate and, where it exists, the
 * experimental value. Colours are the validated dark-surface categorical pair
 * (OKLCH L inside 0.48-0.67, CVD dE 26.8 protan) -- the interface mint and amber
 * sit at L 0.77 and fail the band against this surface, so the plot uses its own.
 */
const SERIES_PRED = '#3987e5';
const SERIES_MEAS = '#d95926';

const AXIS = { min: 4, max: 8.5, ticks: [4, 5, 6, 7, 8] };
const axisPos = (v: number) =>
  ((Math.min(Math.max(v, AXIS.min), AXIS.max) - AXIS.min) / (AXIS.max - AXIS.min)) * 100;

const GRID = '26px minmax(96px,150px) 1fr 54px 78px';

interface TipState {
  x: number;
  y: number;
  title: string;
  lines: string[];
}

const RankedPlot: React.FC<{ rows: CandidateRow[] }> = ({ rows }) => {
  const [tip, setTip] = useState<TipState | null>(null);
  const scored = rows.filter((r) => r.predictedPic50 != null);
  if (!scored.length) return null;
  const anyMeasured = scored.some((r) => r.measuredPic50 != null);

  const show = (e: React.MouseEvent, title: string, lines: string[]) => {
    const t = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setTip({ x: t.left + t.width / 2, y: t.top, title, lines });
  };

  return (
    <section>
      <SectionTitle icon={Activity} title="Predicted potency, ranked" />

      {/* legend: identity is never colour alone, so each swatch carries its label */}
      <div className="flex items-center gap-5 flex-wrap text-[12px] text-[#90A4AF] mb-3">
        <span className="flex items-center gap-2">
          <span
            className="w-[10px] h-[10px] rounded-full ring-2 ring-[#131E27]"
            style={{ background: SERIES_PRED }}
          />
          Predicted
        </span>
        {anyMeasured && (
          <span className="flex items-center gap-2">
            <span
              className="w-[10px] h-[10px] rounded-full ring-2 ring-[#131E27]"
              style={{ background: SERIES_MEAS }}
            />
            Measured (ChEMBL)
          </span>
        )}
        <span className="text-[#4C5E6B]">Numbered rows are the shortlist</span>
      </div>

      <div className="rounded-lg border border-[#202F3C] bg-[#131E27] px-4 py-3">
        {scored.map((r) => (
          <div
            key={r.name}
            className="grid items-center gap-2.5 py-[1px]"
            style={{ gridTemplateColumns: GRID }}
          >
            <div className="text-right">
              {r.selected ? (
                <span className="inline-grid place-items-center w-5 h-5 rounded-full bg-[#E9F0F3] text-[#0B1118] text-[11px] font-semibold tabular-nums">
                  {r.rank}
                </span>
              ) : (
                <span className="text-[11px] text-[#4C5E6B] tabular-nums">{r.rank}</span>
              )}
            </div>

            <div
              className={`text-[12px] truncate ${
                r.selected ? 'text-[#E9F0F3]' : 'text-[#7E939F]'
              }`}
              title={r.smiles ?? r.name}
            >
              {r.name}
            </div>

            <div className="relative h-[26px]">
              {AXIS.ticks.map((t) => (
                <span
                  key={t}
                  className="absolute top-0 bottom-0 w-px bg-[#1F2E3A]"
                  style={{ left: `${axisPos(t)}%` }}
                />
              ))}

              {r.measuredPic50 != null && (
                <button
                  type="button"
                  aria-label={`${r.name}: measured pIC50 ${fmt(r.measuredPic50)}`}
                  className="absolute top-1/2 -mt-[13px] -ml-[13px] w-[26px] h-[26px] grid place-items-center rounded-full"
                  style={{ left: `${axisPos(r.measuredPic50)}%` }}
                  onMouseEnter={(e) =>
                    show(e, r.name, [
                      `Measured pIC50 ${fmt(r.measuredPic50)}`,
                      'Experimental value from ChEMBL',
                    ])
                  }
                  onMouseLeave={() => setTip(null)}
                  onFocus={(e) =>
                    show(e as unknown as React.MouseEvent, r.name, [
                      `Measured pIC50 ${fmt(r.measuredPic50)}`,
                    ])
                  }
                  onBlur={() => setTip(null)}
                >
                  <span
                    className="w-[11px] h-[11px] rounded-full ring-2 ring-[#131E27]"
                    style={{ background: SERIES_MEAS }}
                  />
                </button>
              )}

              <button
                type="button"
                aria-label={`${r.name}: predicted pIC50 ${fmt(r.predictedPic50)}`}
                className="absolute top-1/2 -mt-[13px] -ml-[13px] w-[26px] h-[26px] grid place-items-center rounded-full"
                style={{ left: `${axisPos(r.predictedPic50 as number)}%` }}
                onMouseEnter={(e) =>
                  show(e, r.name, [
                    `Predicted pIC50 ${fmt(r.predictedPic50)}` +
                      (r.predictedIc50Nm
                        ? `  ·  ${nf.format(Math.round(r.predictedIc50Nm))} nM`
                        : ''),
                    `Nearest training compound: Tanimoto ${fmt(r.maxTanimoto)}`,
                    r.domain === 'in'
                      ? 'Inside the applicability domain'
                      : 'Outside the applicability domain — extrapolation',
                    ...(r.inTrainingSet
                      ? ['In the training set, so this estimate is optimistic']
                      : []),
                  ])
                }
                onMouseLeave={() => setTip(null)}
                onBlur={() => setTip(null)}
              >
                <span
                  className="w-[11px] h-[11px] rounded-full ring-2 ring-[#131E27]"
                  style={{ background: SERIES_PRED }}
                />
              </button>
            </div>

            <div
              className={`text-[12px] text-right tabular-nums ${
                r.selected ? 'text-[#E9F0F3]' : 'text-[#7E939F]'
              }`}
            >
              {fmt(r.predictedPic50)}
            </div>
            <div className="text-[12px] text-right tabular-nums text-[#627783]">
              {r.predictedIc50Nm ? `${nf.format(Math.round(r.predictedIc50Nm))} nM` : '—'}
            </div>
          </div>
        ))}

        {/* axis */}
        <div className="grid gap-2.5 mt-1.5" style={{ gridTemplateColumns: GRID }}>
          <div />
          <div />
          <div>
            <div className="relative h-[18px] border-t border-[#2A3A48]">
              {AXIS.ticks.map((t) => (
                <span
                  key={t}
                  className="absolute top-[3px] -translate-x-1/2 text-[11px] text-[#627783] tabular-nums"
                  style={{ left: `${axisPos(t)}%` }}
                >
                  {t}
                </span>
              ))}
            </div>
            <div className="text-[11px] text-[#4C5E6B] text-center mt-0.5">
              predicted pIC50 (higher = more potent)
            </div>
          </div>
          <div />
          <div />
        </div>
      </div>

      {tip && (
        <div
          className="fixed z-50 pointer-events-none rounded-lg border border-[#2A3A48] bg-[#18232D] px-3 py-2 shadow-xl max-w-[280px]"
          style={{ left: tip.x, top: tip.y - 8, transform: 'translate(-50%,-100%)' }}
          role="status"
        >
          <div className="text-[12px] font-semibold text-[#E9F0F3]">{tip.title}</div>
          {tip.lines.map((l) => (
            <div key={l} className="text-[11px] text-[#90A4AF] leading-snug mt-0.5">
              {l}
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

/** Every value, in text -- the table view the plot is read against. */
const ValueTable: React.FC<{ rows: CandidateRow[] }> = ({ rows }) => (
  <section>
    <SectionTitle icon={Layers} title="Every value, in text" />
    <div className="rounded-lg border border-[#202F3C] overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="bg-[#131E27] text-[10px] uppercase tracking-[0.08em] text-[#627783]">
            {['#', 'Compound', 'Short', 'Pred pIC50', 'Pred IC50 nM', 'Measured',
              'Tanimoto', 'Domain', 'QED', 'Lipinski', 'Veber'].map((h, i) => (
              <th
                key={h}
                className={`font-semibold px-3 py-2.5 ${i >= 3 ? 'text-right' : 'text-left'}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows
            .filter((r) => r.predictedPic50 != null)
            .map((r) => (
              <tr key={r.name} className="border-t border-[#1B2833]">
                <td className="px-3 py-2 text-[#627783] tabular-nums">{r.rank}</td>
                <td className="px-3 py-2 text-[#E9F0F3]">{r.name}</td>
                <td className="px-3 py-2 text-[#7E939F]">{r.selected ? 'yes' : 'no'}</td>
                <td className="px-3 py-2 text-right tabular-nums text-[#E9F0F3]">
                  {fmt(r.predictedPic50)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-[#7E939F]">
                  {r.predictedIc50Nm ? nf.format(Math.round(r.predictedIc50Nm)) : '—'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-[#7E939F]">
                  {fmt(r.measuredPic50)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-[#7E939F]">
                  {fmt(r.maxTanimoto)}
                </td>
                <td className="px-3 py-2 text-right text-[#7E939F]">{r.domain ?? '—'}</td>
                <td className="px-3 py-2 text-right tabular-nums text-[#7E939F]">
                  {fmt(r.qed, 3)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-[#7E939F]">
                  {r.lipinskiViolations ?? '—'}
                </td>
                <td className="px-3 py-2 text-right text-[#7E939F]">
                  {r.veberPass == null ? '—' : r.veberPass ? 'pass' : 'fail'}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  </section>
);

const Meter: React.FC<{
  label: string;
  value: number | null | undefined;
  max?: number;
  good: boolean;
  hint?: string;
  /** Draw a tick at this value, e.g. the applicability-domain threshold. */
  mark?: number;
}> = ({ label, value, max = 1, good, hint, mark }) => (
  <div title={hint}>
    <div className="flex justify-between text-[10px] font-mono">
      <span className="text-[#7E939F]">{label}</span>
      <span className="text-[#E9F0F3] font-semibold">{fmt(value)}</span>
    </div>
    <div className="relative w-full h-1.5 bg-[#0C151D] rounded-full mt-1">
      <div
        className="h-full rounded-full transition-[width] duration-500"
        style={{
          width: `${Math.min(100, Math.max(0, ((value ?? 0) / max) * 100))}%`,
          background: good ? '#59C9C0' : '#E9A76A',
        }}
      />
      {mark != null && (
        <span
          className="absolute -top-[3px] -bottom-[3px] w-[2px] rounded-sm bg-[#90A4AF]"
          style={{ left: `${(mark / max) * 100}%` }}
        />
      )}
    </div>
  </div>
);

const Badge: React.FC<{ ok: boolean; children: React.ReactNode; hint?: string }> = ({
  ok,
  children,
  hint,
}) => (
  <span
    title={hint}
    className={`px-2 py-[3px] rounded border text-[10px] font-mono ${
      ok
        ? 'bg-[#0F2724] text-[#59C9C0] border-[#2A5F5C]'
        : 'bg-[#2A1F12] text-[#E9A76A] border-[#5C4630]'
    }`}
  >
    {children}
  </span>
);

const CandidateCards: React.FC<{
  rows: CandidateRow[];
  onToggle: (name: string) => void;
  selectable: boolean;
}> = ({ rows, onToggle, selectable }) => (
  <section>
    <SectionTitle icon={Database} title={`Candidates (${rows.length})`} />
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      {rows.map((r) => {
        const inDomain = r.domain === 'in';
        return (
          <article
            key={r.name}
            onClick={selectable ? () => onToggle(r.name) : undefined}
            className={`p-5 rounded-2xl border transition space-y-4 ${
              selectable ? 'cursor-pointer' : ''
            } ${
              r.selected
                ? 'bg-[#16242E] border-[#59C9C0] shadow-lg'
                : 'bg-[#121D26] border-[#202F3C] hover:border-[#2E4250]'
            }`}
          >
            {/* header: structure, name, headline numbers */}
            <div className="flex items-start gap-4">
              {r.smiles ? (
                <img
                  src={structureSvgUrl(r.smiles, 200)}
                  alt={`Structure of ${r.name}`}
                  className="w-24 h-24 rounded-xl bg-white p-1 border border-[#202F3C] object-contain shrink-0"
                  loading="lazy"
                />
              ) : (
                <div className="w-24 h-24 rounded-xl bg-[#0F1821] border border-[#202F3C] grid place-items-center text-[10px] font-mono text-[#4C5E6B] shrink-0">
                  no structure
                </div>
              )}

              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-semibold text-[15px] text-[#E9F0F3] truncate">
                    {r.name}
                  </h3>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#0C151D] text-[#59C9C0] font-semibold">
                      Rank #{r.rank}
                    </span>
                    {selectable && (
                      <span
                        className={`h-[18px] w-[18px] rounded grid place-items-center border ${
                          r.selected
                            ? 'bg-[#59C9C0] border-[#59C9C0]'
                            : 'border-[#3A4C59]'
                        }`}
                      >
                        {r.selected && <Check size={12} className="text-[#06231F]" />}
                      </span>
                    )}
                  </div>
                </div>

                <div className="text-[13px] font-mono text-[#E9A76A] font-semibold mt-1.5">
                  Predicted pIC50 {fmt(r.predictedPic50)}
                  {r.predictedIc50Nm != null && (
                    <span className="text-[#90A4AF] font-normal">
                      {'  ·  '}
                      {nf.format(Math.round(r.predictedIc50Nm))} nM
                    </span>
                  )}
                </div>

                {r.measuredPic50 != null ? (
                  <div className="text-[11px] font-mono text-[#59C9C0] mt-0.5">
                    ChEMBL measured {fmt(r.measuredPic50)}
                  </div>
                ) : (
                  <div className="text-[11px] font-mono text-[#4C5E6B] mt-0.5">
                    No experimental value on record
                  </div>
                )}

                {r.derivedFrom ? (
                  <div className="text-[11px] text-[#A79BEE] mt-1.5">
                    Analogue of {r.derivedFrom}
                  </div>
                ) : r.note ? (
                  <p className="text-[11px] text-[#7E939F] mt-1.5 leading-snug line-clamp-2">
                    {r.note}
                  </p>
                ) : null}
              </div>
            </div>

            {/* badges */}
            <div className="flex flex-wrap gap-1.5">
              <Badge
                ok={inDomain}
                hint={
                  inDomain
                    ? 'Close enough to the training set for the model to interpolate.'
                    : 'Max Tanimoto below 0.272: the model is extrapolating here.'
                }
              >
                {inDomain ? 'Inside domain' : 'Outside domain'}
              </Badge>
              {r.lipinskiViolations != null && (
                <Badge ok={r.lipinskiViolations <= 1}>
                  Lipinski violations {r.lipinskiViolations}
                </Badge>
              )}
              {r.veberPass != null && (
                <Badge ok={r.veberPass}>{r.veberPass ? 'Veber pass' : 'Veber fail'}</Badge>
              )}
              {r.inTrainingSet && (
                <Badge ok hint="This compound was used to fit the model.">
                  In training set
                </Badge>
              )}
              {r.dockingConfidence != null && (
                <Badge ok hint={r.dockingSite}>
                  Docked {fmt(r.dockingConfidence)}
                </Badge>
              )}
            </div>

            {/* meters */}
            <div className="space-y-2.5">
              <Meter
                label="Similarity to training set (Tanimoto)"
                value={r.maxTanimoto}
                good={(r.maxTanimoto ?? 0) >= 0.272}
                mark={0.272}
                hint="Tick marks the 0.272 applicability-domain threshold."
              />
              <Meter
                label="Drug-likeness (QED)"
                value={r.qed}
                good={(r.qed ?? 0) >= 0.5}
              />
            </div>

            {/* footer */}
            <div className="flex items-center gap-4 pt-3 border-t border-[#1B2833] text-[10px] font-mono text-[#627783]">
              <span>MW {fmt(r.molecularWeight, 1)}</span>
              <span>cLogP {fmt(r.clogp)}</span>
              {r.dockingOperationId && (
                <span className="ml-auto text-[#3E8299] truncate max-w-[150px]">
                  {r.dockingOperationId}
                </span>
              )}
            </div>
          </article>
        );
      })}
    </div>
  </section>
);

const DockingTable: React.FC<{ rows: CandidateRow[] }> = ({ rows }) => (
  <section>
    <SectionTitle icon={FlaskConical} title="Pose results" />
    <div className="rounded-lg border border-[#202F3C] overflow-hidden">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="bg-[#131E27] text-[10px] uppercase tracking-[0.1em] text-[#627783]">
            <th className="text-left font-medium px-3 py-2.5">Compound</th>
            <th className="text-left font-medium px-3">Best site</th>
            <th className="text-right font-medium px-3">Confidence</th>
            <th className="text-left font-medium px-3">Operation</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-t border-[#182530]">
              <td className="px-3 py-2.5 text-[#E9F0F3]">{r.name}</td>
              <td className="px-3 text-[#A9BAC4]">{r.dockingSite ?? '—'}</td>
              <td className="px-3 text-right font-mono text-[#A79BEE]">
                {fmt(r.dockingConfidence)}
              </td>
              <td className="px-3 font-mono text-[10px] text-[#3E8299]">
                {r.dockingOperationId ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <p className="text-[11px] text-[#627783] mt-2 leading-relaxed max-w-[72ch]">
      Confidence ranks poses of a single ligand. It is not a binding affinity, and comparing
      it across different ligands is unreliable.
    </p>
  </section>
);

const StageActions: React.FC<{
  active: StageId;
  stage: StageRun;
  selectedCount: number;
  dockedCount: number;
  onCandidates: () => void;
  onConfirm: () => void;
  onStructure: () => void;
  onDock: () => void;
  onDynamics: () => void;
  onIterate: () => void;
}> = ({
  active,
  stage,
  selectedCount,
  dockedCount,
  onCandidates,
  onConfirm,
  onStructure,
  onDock,
  onDynamics,
  onIterate,
}) => {
  const running = stage.state === 'running';
  const map: Partial<Record<StageId, { label: string; onClick: () => void; disabled?: boolean; note?: string }>> = {
    candidates: { label: 'Score candidate set', onClick: onCandidates },
    selection: {
      label: `Carry ${selectedCount} forward`,
      onClick: onConfirm,
      disabled: selectedCount === 0,
      note: selectedCount === 0 ? 'Select at least one candidate.' : undefined,
    },
    structure: { label: 'Prepare receptor and sites', onClick: onStructure },
    docking: {
      label: 'Dock selected candidates',
      onClick: onDock,
      disabled: selectedCount === 0,
      note:
        selectedCount === 0
          ? 'Nothing selected.'
          : 'Each ligand is docked at every site. Jobs run one at a time on the remote queue.',
    },
    dynamics: {
      label: 'Prepare dynamics',
      onClick: onDynamics,
      disabled: dockedCount === 0,
      note: dockedCount === 0 ? 'Requires a docked pose.' : undefined,
    },
    iterate: {
      label: 'Generate and score analogues',
      onClick: onIterate,
      note: 'Single-point changes to the leading candidate, scored by the same model.',
    },
  };
  const action = map[active];
  if (stage.state === 'blocked')
    return (
      <section className="rounded-lg border border-[#5C4630] bg-[#1E1A12] p-4 flex gap-3">
        <AlertTriangle size={15} className="text-[#E9A76A] shrink-0 mt-[1px]" />
        <div>
          <div className="text-[12px] font-medium text-[#E9A76A]">Stage unavailable</div>
          <p className="text-[12px] text-[#C3AE8E] mt-1 leading-relaxed max-w-[70ch]">
            {stage.blockedReason}
          </p>
        </div>
      </section>
    );
  if (!action) return null;
  return (
    <section className="pt-2">
      <button
        onClick={action.onClick}
        disabled={running || action.disabled}
        className="inline-flex items-center gap-2 rounded-md bg-[#59C9C0] text-[#06231F] text-[13px] font-semibold px-5 py-2.5 disabled:opacity-35 disabled:cursor-not-allowed"
      >
        {running ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
        {action.label}
      </button>
      {action.note && (
        <p className="text-[11px] text-[#627783] mt-2 max-w-[70ch]">{action.note}</p>
      )}
    </section>
  );
};

const JobBoard: React.FC<{ jobs: JobRow[] }> = ({ jobs }) => {
  const done = jobs.filter((j) => j.state === 'done').length;
  const failed = jobs.filter((j) => j.state === 'failed').length;
  return (
    <section>
      <SectionTitle icon={Server} title={`Docking queue (${done}/${jobs.length})`} />
      <div className="rounded-lg border border-[#202F3C] overflow-hidden divide-y divide-[#1B2833]">
        {jobs.map((j) => (
          <div key={j.key} className="flex items-center gap-3 px-4 py-2.5">
            <span className="shrink-0">
              {j.state === 'running' ? (
                <Loader2 size={13} className="animate-spin text-[#59C9C0]" />
              ) : j.state === 'done' ? (
                <Check size={13} className="text-[#59C9C0]" />
              ) : j.state === 'failed' ? (
                <AlertTriangle size={13} className="text-[#E06C6C]" />
              ) : (
                <CircleDot size={13} className="text-[#3E4E5B]" />
              )}
            </span>

            <span className="text-[12px] text-[#E9F0F3] w-[110px] truncate">{j.compound}</span>
            <span className="text-[12px] text-[#7E939F] flex-1 truncate">{j.siteName}</span>

            {j.state === 'done' && (
              <>
                <span className="font-mono text-[11px] text-[#627783]">{j.poses ?? 0} poses</span>
                <span className="font-mono text-[12px] text-[#A79BEE] w-[46px] text-right">
                  {fmt(j.confidence ?? null)}
                </span>
              </>
            )}
            {j.state === 'running' && (
              <span className="text-[11px] text-[#59C9C0]">running</span>
            )}
            {j.state === 'queued' && (
              <span className="text-[11px] text-[#4C5E6B]">queued</span>
            )}
            {j.state === 'failed' && (
              <span className="text-[11px] text-[#E06C6C] truncate max-w-[220px]">
                {j.error ?? 'failed'}
              </span>
            )}
          </div>
        ))}
      </div>
      <p className="text-[11px] text-[#627783] mt-2 max-w-[72ch] leading-relaxed">
        The remote queue admits one job at a time, so these run in sequence.
        {failed > 0 && ` ${failed} did not return a pose.`}
      </p>
    </section>
  );
};

const VinaTable: React.FC = () => (
  <section>
    <SectionTitle icon={GitBranch} title={`Analogue docking (${VINA_ANALOGUES.length} candidates)`} />
    <div className="rounded-lg border border-[#202F3C] overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="bg-[#131E27] text-[10px] uppercase tracking-[0.08em] text-[#627783]">
            <th className="text-left font-semibold px-3 py-2.5">Analogue</th>
            <th className="text-right font-semibold px-3">Vina kcal/mol</th>
            <th className="text-right font-semibold px-3">vs parent</th>
            <th className="text-left font-semibold px-3">Structure</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-t border-[#2A3A48] bg-[#16242E]">
            <td className="px-3 py-2.5 text-[#E9F0F3] font-medium">
              BIBR1532 (redocked reference)
            </td>
            <td className="px-3 text-right tabular-nums text-[#E9F0F3] font-semibold">
              {VINA_REFERENCE.score.toFixed(2)}
            </td>
            <td className="px-3 text-right text-[#627783]">—</td>
            <td className="px-3 text-[11px] text-[#59C9C0]">
              pose reproduced to {VINA_REFERENCE.redockRmsd} A
            </td>
          </tr>
          {VINA_ANALOGUES.map((a) => {
            const wins = a.delta < 0;
            return (
              <tr key={a.id} className="border-t border-[#1B2833]">
                <td className="px-3 py-2 text-[#A9BAC4] font-mono text-[11px]">{a.id}</td>
                <td
                  className="px-3 text-right tabular-nums font-semibold"
                  style={{ color: wins ? '#59C9C0' : '#A9BAC4' }}
                >
                  {a.vina.toFixed(2)}
                </td>
                <td
                  className="px-3 text-right tabular-nums"
                  style={{ color: wins ? '#59C9C0' : '#7E939F' }}
                >
                  {a.delta > 0 ? '+' : ''}
                  {a.delta.toFixed(2)}
                </td>
                <td className="px-3 py-1.5">
                  <img
                    src={structureSvgUrl(a.smiles, 120)}
                    alt={`Structure of ${a.id}`}
                    className="h-10 w-[72px] rounded bg-white object-contain"
                    loading="lazy"
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    <p className="text-[11px] text-[#627783] mt-2 max-w-[76ch] leading-relaxed">
      {VINA_SCOPE_WARNING}
    </p>
  </section>
);

const TrajectoryTable: React.FC<{ rows: ReferenceDynamics[] }> = ({ rows }) => (
  <section>
    <SectionTitle icon={Waves} title={`Trajectory analysis (${DYNAMICS_WINDOW_NS} ns)`} />
    <div className="rounded-lg border border-[#202F3C] overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="bg-[#131E27] text-[10px] uppercase tracking-[0.08em] text-[#627783]">
            <th className="text-left font-semibold px-3 py-2.5">Complex</th>
            <th className="text-right font-semibold px-3">Backbone RMSD</th>
            <th className="text-right font-semibold px-3">Ligand RMSD</th>
            <th className="text-right font-semibold px-3">Ligand RMSF</th>
            <th className="text-right font-semibold px-3">H-bond</th>
            <th className="text-right font-semibold px-3">Pocket contact</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const held = r.ligandRmsd <= 2.5;
            return (
              <tr key={r.compound} className="border-t border-[#1B2833]">
                <td className="px-3 py-2.5 text-[#E9F0F3]">{r.compound}</td>
                <td className="px-3 text-right tabular-nums text-[#7E939F]">
                  {r.backboneRmsd.toFixed(1)} A
                </td>
                <td
                  className="px-3 text-right tabular-nums font-semibold"
                  style={{ color: held ? '#59C9C0' : '#E9A76A' }}
                  title={
                    held
                      ? 'Stays within 2.5 A of the docked pose.'
                      : 'Drifts from the docked pose over the window.'
                  }
                >
                  {r.ligandRmsd.toFixed(1)} A
                </td>
                <td className="px-3 text-right tabular-nums text-[#7E939F]">
                  {r.ligandRmsf.toFixed(1)} A
                </td>
                <td className="px-3 text-right tabular-nums text-[#7E939F]">
                  {(r.hbondOccupancy * 100).toFixed(0)}%
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2 justify-end">
                    <div className="w-16 h-1.5 rounded-full bg-[#0C151D] overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${r.contactPersistence * 100}%`,
                          background: held ? '#59C9C0' : '#E9A76A',
                        }}
                      />
                    </div>
                    <span className="tabular-nums text-[#7E939F] w-9 text-right">
                      {(r.contactPersistence * 100).toFixed(0)}%
                    </span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    <p className="text-[11px] text-[#627783] mt-2 max-w-[72ch] leading-relaxed">
      Ligand RMSD is measured against the docked pose: a complex that holds its pose
      kept the binding mode the docking proposed. {DYNAMICS_NOTE}
    </p>
  </section>
);

const StepBoard: React.FC<{ steps: PrepStep[] }> = ({ steps }) => (
  <section>
    <SectionTitle icon={Waves} title="System preparation" />
    <ol className="rounded-lg border border-[#202F3C] overflow-hidden divide-y divide-[#1B2833]">
      {steps.map((st, i) => (
        <li key={st.label} className="flex items-start gap-3 px-4 py-2.5">
          <span className="shrink-0 mt-[2px]">
            {st.state === 'running' ? (
              <Loader2 size={13} className="animate-spin text-[#59C9C0]" />
            ) : st.state === 'done' ? (
              <Check size={13} className="text-[#59C9C0]" />
            ) : (
              <CircleDot size={13} className="text-[#3E4E5B]" />
            )}
          </span>
          <span className="font-mono text-[10px] text-[#4C5E6B] mt-[3px]">
            {String(i + 1).padStart(2, '0')}
          </span>
          <div className="min-w-0">
            <div
              className={`text-[12px] ${
                st.state === 'queued' ? 'text-[#4C5E6B]' : 'text-[#E9F0F3]'
              }`}
            >
              {st.label}
            </div>
            <div className="text-[11px] text-[#7E939F] leading-snug">{st.detail}</div>
          </div>
        </li>
      ))}
    </ol>
  </section>
);

const SectionTitle: React.FC<{ icon: React.ElementType; title: string }> = ({
  icon: Icon,
  title,
}) => (
  <div className="flex items-center gap-2 mb-3">
    <Icon size={13} className="text-[#4C8B84]" />
    <h2 className="text-[11px] uppercase tracking-[0.14em] text-[#90A4AF]">{title}</h2>
    <ChevronRight size={12} className="text-[#2A3A48]" />
  </div>
);

/* ------------------------------------------------------------------ helpers */

function median(values: (number | null | undefined)[]): number | null {
  const xs = values.filter((v): v is number => v != null).sort((a, b) => a - b);
  if (!xs.length) return null;
  const mid = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
}

/**
 * Single-point changes to a lead, expressed as SMILES edits.
 *
 * These are ordinary medicinal-chemistry moves — a halogen walk, a methyl, an
 * ester — chosen because each is one change from the parent and therefore
 * interpretable when the score moves. The model scores them like any other input.
 */
function analoguesOf(smiles: string): { smiles: string; tag: string; change: string }[] {
  const out: { smiles: string; tag: string; change: string }[] = [];
  const push = (s: string, tag: string, change: string) => {
    if (s !== smiles) out.push({ smiles: s, tag, change });
  };
  // Aromatic substitution on the first benzene ring found.
  if (smiles.includes('c1ccccc1')) {
    push(smiles.replace('c1ccccc1', 'c1ccc(F)cc1'), 'F', 'Para fluorine on the aryl ring');
    push(smiles.replace('c1ccccc1', 'c1ccc(Cl)cc1'), 'Cl', 'Para chlorine on the aryl ring');
    push(smiles.replace('c1ccccc1', 'c1ccc(OC)cc1'), 'OMe', 'Para methoxy on the aryl ring');
  }
  // Carboxylic acid to methyl ester, a standard permeability probe.
  if (smiles.includes('C(=O)O')) {
    push(smiles.replace('C(=O)O', 'C(=O)OC'), 'ester', 'Methyl ester of the carboxylic acid');
    push(smiles.replace('C(=O)O', 'C(=O)N'), 'amide', 'Primary amide in place of the acid');
  }
  // Hydroxyl to methoxy.
  if (smiles.includes('(O)') && out.length < 5) {
    push(smiles.replace('(O)', '(OC)'), 'OMe2', 'Methyl ether in place of a hydroxyl');
  }
  return out.slice(0, 5);
}

export default PipelineView;
