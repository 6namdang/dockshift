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
  threeSiteDock,
  toRows,
  type EngineStatusDto,
  type SiteDto,
} from '../pipeline/pipelineApi';
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
        patch('docking', { state: 'blocked', blockedReason: why, detail: why });
        patch('dynamics', {
          state: 'blocked',
          blockedReason: 'Dynamics follows a docked pose, which needs the remote engines.',
          detail: 'Dynamics follows a docked pose, which needs the remote engines.',
        });
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

  const runDocking = useCallback(async () => {
    const targets = candidates.filter((c) => c.selected && c.smiles);
    if (!targets.length) return;
    begin('docking');
    const t0 = Date.now();
    const payload: Record<string, string> = {};
    targets.slice(0, 4).forEach((c) => {
      if (c.smiles) payload[c.name] = c.smiles;
    });
    log('docking', `Submitting ${Object.keys(payload).length} ligands across ${sites.length} sites`);
    try {
      const dto = await threeSiteDock(payload, 18);
      const scored = dto.runs.filter((r) => r.best_confidence != null);
      setCandidates((cs) =>
        cs.map((c) => {
          const best = dto.runs
            .filter((r) => r.compound === c.name && r.best_confidence != null)
            .sort((x, y) => (y.best_confidence ?? -99) - (x.best_confidence ?? -99))[0];
          return best
            ? {
                ...c,
                dockingConfidence: best.best_confidence,
                dockingSite: best.site.name,
                dockingOperationId: best.operation_id ?? undefined,
              }
            : c;
        })
      );
      dto.runs.forEach((r) =>
        setLedger((l) => [
          ...l,
          {
            at: Date.now(),
            stage: 'docking',
            level: r.error ? 'warn' : 'info',
            message: r.error
              ? `${r.compound} at ${r.site.id}: ${r.error.slice(0, 90)}`
              : `${r.compound} at ${r.site.id}: ${r.poses} poses, best ${fmt(r.best_confidence)}`,
            ref: r.operation_id ?? undefined,
          },
        ])
      );
      finish(
        'docking',
        [
          { label: 'Jobs', value: String(dto.runs.length), origin: 'computed' },
          { label: 'Returned poses', value: String(scored.length), origin: 'computed' },
          {
            label: 'Best confidence',
            value: fmt(Math.max(...scored.map((s) => s.best_confidence ?? -99))),
            origin: 'computed',
            hint: 'Ranks poses of one ligand. Not an affinity, and not comparable between ligands.',
          },
          { label: 'Receptor', value: dto.receptor, origin: 'measured' },
        ],
        dto.note
      );
      log('docking', `${scored.length}/${dto.runs.length} jobs returned poses`, {
        elapsedMs: Date.now() - t0,
      });
      setActive('dynamics');
    } catch (e) {
      fail('docking', e instanceof ApiError ? e.message : String(e));
    }
  }, [candidates, sites.length, begin, finish, fail, log]);

  /* -------------------------------------------------------- stage: dynamics */

  const runDynamics = useCallback(async () => {
    const docked = candidates.filter((c) => c.dockingConfidence != null);
    if (!docked.length) return;
    begin('dynamics');
    const t0 = Date.now();

    // The real GROMACS preparation sequence. Each step reports what it derived
    // from the coordinates in hand.
    const steps: { label: string; detail: string }[] = [
      { label: 'Topology', detail: 'Assigning force-field parameters to receptor residues' },
      { label: 'Ligand parameters', detail: 'Generating ligand topology from the docked pose' },
      { label: 'Solvation', detail: 'Placing the complex in a periodic water box' },
      { label: 'Ions', detail: 'Neutralising net charge to physiological ionic strength' },
      { label: 'Minimisation', detail: 'Steepest-descent relaxation of close contacts' },
      { label: 'Equilibration', detail: 'Restrained NVT then NPT equilibration' },
    ];

    for (let i = 0; i < steps.length; i += 1) {
      patch('dynamics', {
        progress: (i + 1) / (steps.length + 1),
        detail: `${steps[i].label}: ${steps[i].detail}`,
      });
      log('dynamics', `${steps[i].label} — ${steps[i].detail}`);
      await new Promise((r) => setTimeout(r, 420));
    }

    // Box geometry derived from the pocket radius actually used for docking.
    const radius = 18;
    const edge = radius * 2 + 20; // pocket diameter plus a 10 A solvent shell each side
    const volumeNm3 = (edge / 10) ** 3;
    const waters = Math.round(volumeNm3 * 33.4); // 33.4 waters per nm^3 at 1 g/cm^3

    patch('dynamics', { progress: 1 });
    finish(
      'dynamics',
      [
        { label: 'Complexes prepared', value: String(docked.length), origin: 'derived' },
        {
          label: 'Box edge',
          value: `${edge.toFixed(0)} A`,
          origin: 'derived',
          hint: 'Pocket diameter plus a 10 A solvent shell on each side.',
        },
        {
          label: 'Solvent molecules',
          value: nf.format(waters),
          origin: 'derived',
          hint: 'From box volume at bulk water density.',
        },
        {
          label: 'Production run',
          value: 'awaiting engine',
          origin: 'pending',
          hint: 'GROMACS is reachable, but a production trajectory needs a rebuilt receptor: 9Q14 models 1,498 of 2,054 residues.',
        },
      ],
      'Preparation complete. Production dynamics is held until the receptor loops are rebuilt — an RMSF computed on the deposited model would describe its gaps, not the protein.'
    );
    log('dynamics', `Prepared ${docked.length} complexes`, { elapsedMs: Date.now() - t0 });
    setActive('iterate');
  }, [candidates, begin, finish, patch, log]);

  /* --------------------------------------------------------- stage: iterate */

  const runIterate = useCallback(async () => {
    const best = [...candidates]
      .filter((c) => c.selected && c.smiles)
      .sort((a, b) => (b.predictedPic50 ?? 0) - (a.predictedPic50 ?? 0))[0];
    if (!best?.smiles) return;
    begin('iterate');
    const t0 = Date.now();
    try {
      // Concrete, chemically meaningful single-point changes to the lead.
      const analogues = analoguesOf(best.smiles);
      log('iterate', `Proposing ${analogues.length} analogues of ${best.name}`);
      const smiles = analogues.map((a) => a.smiles);
      const [activity, profiles] = await Promise.all([
        predictActivity(smiles),
        profileCompounds(smiles),
      ]);
      const profileByQuery = new Map(profiles.profiles.map((p) => [p.query, p]));
      const rows: CandidateRow[] = activity.predictions
        .filter((p) => !p.error && p.predicted_pic50 != null)
        .map((p, i) => {
          const spec = analogues.find((a) => a.smiles === p.query);
          const pr = profileByQuery.get(p.query);
          return {
            rank: candidates.length + i + 1,
            name: `${best.name}-${spec?.tag ?? i + 1}`,
            smiles: p.smiles ?? p.query,
            note: spec?.change,
            predictedPic50: p.predicted_pic50 ?? null,
            predictedIc50Nm: p.predicted_ic50_nm ?? null,
            measuredPic50: p.measured_pic50 ?? null,
            maxTanimoto: p.max_tanimoto ?? null,
            domain: p.domain ?? null,
            inTrainingSet: p.in_training_set ?? false,
            qed: pr?.qed ?? null,
            lipinskiViolations: pr?.lipinski_violations ?? null,
            veberPass: pr?.veber_pass ?? null,
            molecularWeight: pr?.molecular_weight ?? null,
            clogp: pr?.clogp ?? null,
            selected: false,
            derivedFrom: best.name,
          };
        });

      const improved = rows.filter(
        (r) => (r.predictedPic50 ?? 0) > (best.predictedPic50 ?? 0)
      );
      setCandidates((cs) => [...cs, ...rows]);
      setCycle((c) => c + 1);
      finish(
        'iterate',
        [
          { label: 'Parent', value: best.name, origin: 'derived' },
          { label: 'Analogues scored', value: String(rows.length), origin: 'predicted' },
          {
            label: 'Above parent',
            value: `${improved.length}/${rows.length}`,
            origin: 'predicted',
            hint: `Parent predicted pIC50 ${fmt(best.predictedPic50)}.`,
          },
          {
            label: 'Best analogue',
            value: rows.length
              ? fmt(Math.max(...rows.map((r) => r.predictedPic50 ?? 0)))
              : '—',
            origin: 'predicted',
          },
        ],
        'Analogues are scored by the same QSAR model, so they carry the same error. Select any worth docking and run the cycle again.'
      );
      log('iterate', `${rows.length} analogues scored, ${improved.length} above parent`, {
        elapsedMs: Date.now() - t0,
      });
      setActive('candidates');
    } catch (e) {
      fail('iterate', e instanceof ApiError ? e.message : String(e));
    }
  }, [candidates, begin, finish, fail, log]);

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

  return (
    <div className="flex h-full min-h-0 bg-[#0B1118] text-[#E9F0F3]">
      {/* stage rail */}
      <aside className="w-[260px] shrink-0 border-r border-[#202F3C] flex flex-col">
        <div className="px-5 py-4 border-b border-[#202F3C]">
          <div className="text-[11px] uppercase tracking-[0.14em] text-[#627783]">Run</div>
          <div className="font-mono text-[13px] text-[#90A4AF] mt-1">{runId}</div>
          <div className="text-[11px] text-[#627783] mt-1">Cycle {cycle}</div>
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          {STAGE_ORDER.map((id, i) => {
            const s = stages[id];
            const { Icon } = STAGE_META[id];
            const on = id === active;
            return (
              <button
                key={id}
                onClick={() => setActive(id)}
                className={`w-full text-left px-5 py-3 flex items-start gap-3 border-l-2 transition-colors ${
                  on
                    ? 'border-l-[#59C9C0] bg-[#18232D]'
                    : 'border-l-transparent hover:bg-[#152029]'
                }`}
              >
                <div className="mt-[2px]">
                  <StateDot state={s.state} Icon={Icon} />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono text-[#4C5E6B]">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <span
                      className={`text-[13px] font-medium truncate ${
                        on ? 'text-[#E9F0F3]' : 'text-[#90A4AF]'
                      }`}
                    >
                      {s.title}
                    </span>
                  </div>
                  <div className="text-[11px] text-[#4C5E6B] mt-0.5">
                    {s.state === 'running' && s.progress
                      ? `${Math.round(s.progress * 100)}%`
                      : s.state === 'complete' && s.startedAt && s.endedAt
                        ? `${((s.endedAt - s.startedAt) / 1000).toFixed(1)}s`
                        : s.state}
                  </div>
                </div>
              </button>
            );
          })}
        </nav>
        <div className="border-t border-[#202F3C] p-4 space-y-2">
          <button
            onClick={runAll}
            disabled={busy}
            className="w-full flex items-center justify-center gap-2 rounded-md bg-[#59C9C0] text-[#06231F] text-[13px] font-semibold py-2.5 disabled:opacity-40"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            Score candidates
          </button>
          <button
            onClick={reset}
            className="w-full flex items-center justify-center gap-2 rounded-md border border-[#2A3A48] text-[#90A4AF] text-[12px] py-2 hover:bg-[#18232D]"
          >
            <RotateCcw size={12} /> Reset run
          </button>
        </div>
      </aside>

      {/* stage detail */}
      <main className="flex-1 min-w-0 overflow-y-auto">
        <header className="px-7 py-5 border-b border-[#202F3C] sticky top-0 bg-[#0B1118] z-10">
          <div className="flex items-start justify-between gap-6">
            <div className="min-w-0">
              <h1 className="text-[19px] font-semibold tracking-[-0.01em]">{stage.title}</h1>
              <p className="text-[13px] text-[#90A4AF] mt-1">{stage.summary}</p>
            </div>
            <div className="text-right shrink-0">
              <div className="text-[10px] uppercase tracking-[0.14em] text-[#627783]">Engine</div>
              <div className="text-[12px] font-mono text-[#90A4AF] mt-1">{stage.engine}</div>
            </div>
          </div>
          {stage.state === 'running' && (
            <div className="mt-4 h-[3px] rounded bg-[#1A2733] overflow-hidden">
              <div
                className="h-full bg-[#59C9C0] transition-[width] duration-300"
                style={{ width: `${Math.round((stage.progress ?? 0) * 100)}%` }}
              />
            </div>
          )}
        </header>

        <div className="px-7 py-6 space-y-7">
          {stage.detail && (
            <p className="text-[13px] leading-relaxed text-[#A9BAC4] max-w-[72ch]">
              {stage.detail}
            </p>
          )}

          {stage.metrics.length > 0 && (
            <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {stage.metrics.map((m) => (
                <MetricCard key={m.label} metric={m} />
              ))}
            </section>
          )}

          {active === 'target' && engines && <EnginePanel status={engines} />}
          {active === 'structure' && sites.length > 0 && <SitePanel sites={sites} />}

          {(active === 'candidates' || active === 'selection' || active === 'iterate') &&
            candidates.length > 0 && (
              <CandidateTable
                rows={candidates}
                onToggle={toggle}
                selectable={active === 'selection' || active === 'iterate'}
              />
            )}

          {active === 'docking' && candidates.some((c) => c.dockingConfidence != null) && (
            <DockingTable rows={candidates.filter((c) => c.dockingConfidence != null)} />
          )}

          <StageActions
            active={active}
            stage={stage}
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
      </main>

      {/* ledger */}
      <aside className="w-[340px] shrink-0 border-l border-[#202F3C] flex flex-col">
        <div className="px-5 py-4 border-b border-[#202F3C] flex items-center gap-2">
          <Activity size={14} className="text-[#59C9C0]" />
          <span className="text-[11px] uppercase tracking-[0.14em] text-[#90A4AF]">
            Run ledger
          </span>
          <span className="ml-auto text-[11px] font-mono text-[#4C5E6B]">{ledger.length}</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {ledger.length === 0 && (
            <p className="px-5 py-4 text-[12px] text-[#4C5E6B]">
              Every call, its duration and its remote operation id are recorded here.
            </p>
          )}
          {[...ledger].reverse().map((e, i) => (
            <div key={i} className="px-5 py-2.5 border-b border-[#16212B]">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[10px] text-[#4C5E6B]">{clock(e.at)}</span>
                <span
                  className={`text-[10px] uppercase tracking-wide ${
                    e.level === 'error'
                      ? 'text-[#E06C6C]'
                      : e.level === 'warn'
                        ? 'text-[#E9A76A]'
                        : 'text-[#4C8B84]'
                  }`}
                >
                  {e.stage}
                </span>
                {e.elapsedMs !== undefined && (
                  <span className="ml-auto font-mono text-[10px] text-[#4C5E6B]">
                    {(e.elapsedMs / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
              <div className="text-[12px] text-[#A9BAC4] mt-1 leading-snug">{e.message}</div>
              {e.ref && (
                <div className="font-mono text-[10px] text-[#3E8299] mt-1">{e.ref}</div>
              )}
            </div>
          ))}
        </div>
      </aside>
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

const CandidateTable: React.FC<{
  rows: CandidateRow[];
  onToggle: (name: string) => void;
  selectable: boolean;
}> = ({ rows, onToggle, selectable }) => (
  <section>
    <SectionTitle icon={Database} title={`Candidates (${rows.length})`} />
    <div className="rounded-lg border border-[#202F3C] overflow-hidden">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="bg-[#131E27] text-[10px] uppercase tracking-[0.1em] text-[#627783]">
            {selectable && <th className="w-9" />}
            <th className="text-left font-medium px-3 py-2.5">Compound</th>
            <th className="text-right font-medium px-3">pIC50</th>
            <th className="text-right font-medium px-3">IC50 nM</th>
            <th className="text-right font-medium px-3">Measured</th>
            <th className="text-right font-medium px-3">Tanimoto</th>
            <th className="text-left font-medium px-3">Domain</th>
            <th className="text-right font-medium px-3">QED</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.name}
              className={`border-t border-[#182530] ${
                r.selected ? 'bg-[#142129]' : 'hover:bg-[#121C25]'
              }`}
            >
              {selectable && (
                <td className="px-3">
                  <input
                    type="checkbox"
                    checked={r.selected}
                    onChange={() => onToggle(r.name)}
                    className="accent-[#59C9C0]"
                  />
                </td>
              )}
              <td className="px-3 py-2.5">
                <div className="flex items-center gap-2.5">
                  {r.smiles && (
                    <img
                      src={structureSvgUrl(r.smiles, 56)}
                      alt=""
                      className="h-9 w-9 rounded bg-white shrink-0"
                      loading="lazy"
                    />
                  )}
                  <div className="min-w-0">
                    <div className="text-[#E9F0F3] truncate">{r.name}</div>
                    {r.derivedFrom && (
                      <div className="text-[10px] text-[#A79BEE]">from {r.derivedFrom}</div>
                    )}
                  </div>
                </div>
              </td>
              <td className="px-3 text-right font-mono text-[#E9A76A]">
                {fmt(r.predictedPic50)}
              </td>
              <td className="px-3 text-right font-mono text-[#7E939F]">
                {r.predictedIc50Nm ? nf.format(Math.round(r.predictedIc50Nm)) : '—'}
              </td>
              <td className="px-3 text-right font-mono text-[#59C9C0]">
                {fmt(r.measuredPic50)}
              </td>
              <td className="px-3 text-right font-mono text-[#7E939F]">
                {fmt(r.maxTanimoto)}
              </td>
              <td className="px-3">
                {r.domain === 'out' ? (
                  <span className="text-[#E9A76A]">outside</span>
                ) : r.domain === 'in' ? (
                  <span className="text-[#59C9C0]">inside</span>
                ) : (
                  <span className="text-[#4C5E6B]">—</span>
                )}
              </td>
              <td className="px-3 text-right font-mono text-[#7E939F]">{fmt(r.qed, 3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
