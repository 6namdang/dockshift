import React, { useEffect, useState } from 'react';
import { CollectiveControls, CollectiveReport } from '../integration/CollectiveWorkflow';
import {
  ManagedCapabilities as AgentCapabilities, ManagedRunResult as AgentRunResult, ResearchProgress,
  fetchResearchCapabilities, fetchResearchReport,
  fetchResearchProgress, startResearch, resumeResearch, downloadResearchArtifact,
} from '../integration/researchApi';

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AgentReport({ report, token = '' }: { report: AgentRunResult; token?: string }) {
  const [error, setError] = useState('');
  const outputs = report.outputs;
  return <section aria-label="Agent run report" className="space-y-4">
    <h2 className="text-lg font-semibold">Run {report.status}</h2>
    {report.candidate_screening_status && <p>Candidate screen: {report.candidate_screening_status} · Full scientific workflow: {report.status}</p>}
    <p className="text-sm text-[#90A4AF] break-all">{report.run_id}</p>
    <p>Ledger: {report.ledger_integrity.verified ? 'verified' : 'integrity failure'} ·
      LLM workers invoked: {report.llm_agents_invoked}/8 · Scientific review: {report.scientific_review}</p>
    <div className="overflow-x-auto"><table className="w-full text-left text-sm">
      <thead><tr>{['Agent', 'Science', 'Agent review', 'Evidence / blocker'].map(h =>
        <th key={h} className="p-2 border-b border-[#202F3C]">{h}</th>)}</tr></thead>
      <tbody>{report.agents.map(a => <tr key={a.agent}>
        <td className="p-2">{a.agent} · {a.role}</td>
        <td className="p-2">{a.scientific_status}</td><td className="p-2">{a.agent_status}</td>
        <td className="p-2">{a.detail}</td>
      </tr>)}</tbody>
    </table></div>
    <h3 className="font-semibold">Computed evidence</h3>
    {outputs?.collective && <CollectiveReport output={outputs.collective} runId={report.run_id} token={token} />}
    {report.computational_evidence.length === 0 ? <p>No computed metrics were recorded.</p>
      : <ul>{report.computational_evidence.map((m, i) =>
        <li key={i}>{m.agent}: {m.metric} = {m.value} {m.unit} · {m.method}</li>)}</ul>}
    {outputs?.screening && <div>
      <h3>Dockshift QSAR and chemical validation</h3>
      {outputs.screening.qsar.predictions.map((p, i) => <div key={i} className="p-3 border rounded space-y-1">
        <p className="break-all">Canonical SMILES: {p.smiles}</p>
        <p>Predicted pIC50: {p.predicted_pic50 ?? 'not computed'} · Applicability domain: {p.domain ?? 'unknown'}</p>
        <p>Measured ChEMBL pIC50: {p.measured_pic50 ?? 'not available'} · In training set: {p.in_training_set ? 'yes' : 'no'}</p>
        <p>Prediction for ranking and triage; approximately 0.5 log unit model error.</p>
      </div>)}
    </div>}
    {outputs?.admet && <section className="space-y-2">
      <h3>Nebius ADMET-AI {outputs.admet.model_version}</h3><p>{outputs.admet.validation}</p>
      <table className="w-full text-sm text-left"><thead><tr><th>Endpoint</th><th>Prediction</th><th>Units</th><th>Species</th></tr></thead>
        <tbody>{outputs.admet.endpoints?.map(e => <tr key={e.endpoint}>
          <td>{e.endpoint}</td><td>{e.value}</td><td>{e.units}</td><td>{e.species}</td>
        </tr>)}</tbody></table>
      <p>Target-independent model predictions; no human safety or efficacy claim.</p>
      {outputs.admet.artifacts.map(a => <details key={a.filename} className="border rounded p-3">
        <summary>{a.filename} · {a.size_bytes} bytes · SHA-256 verified</summary>
        <p className="break-all text-xs">{a.sha256}</p>
        <pre className="overflow-auto text-xs max-h-96">{JSON.stringify(a.data, null, 2)}</pre>
        <button disabled={!token} className="border p-2 rounded" onClick={async () => {
          try { saveBlob(await downloadResearchArtifact(report.run_id, a.filename, token), a.filename); }
          catch (e) { setError(String(e)); }
        }}>Download verified scientific artifact</button>
      </details>)}
    </section>}
    {outputs?.admet_operation?.status === 'PENDING' && <p>ADMET operation pending: {outputs.admet_operation.operation_id}</p>}
    {outputs?.literature && <section><h3>Literature: {outputs.literature.retrieval_status}</h3>
      <ul>{outputs.literature.results.map((p, i) => <li key={i}>
        {p.url ? <a className="underline" href={p.url} target="_blank" rel="noreferrer">{p.title}</a> : p.title} · {p.source}
      </li>)}</ul>
      {outputs.literature.errors.map((e, i) => <p key={i}>Source unavailable: {e.source} · {e.message}</p>)}
    </section>}
    {outputs && <details><summary>Input identity, software versions, profiles and provenance</summary>
      <pre className="text-xs overflow-auto max-h-96">{JSON.stringify(outputs, null, 2)}</pre>
    </details>}
    <p className="text-sm text-[#90A4AF]">{report.separation_statement}</p>
    {error && <p role="alert">{error}</p>}
    <button className="border rounded p-2" onClick={() => saveBlob(
      new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }), `${report.run_id}.json`,
    )}>Download evidence report</button>
  </section>;
}

export function AgentRunsView({ candidate }: { candidate?: { name: string; smiles?: string } }) {
  const [capabilities, setCapabilities] = useState<AgentCapabilities | null>(null);
  const [token, setToken] = useState('');
  const [compound, setCompound] = useState(candidate?.smiles || candidate?.name || 'BIBR1532');
  const [query, setQuery] = useState('hTERT BIBR1532');
  const [llm, setLlm] = useState(false);
  const [docking, setDocking] = useState(false);
  const [preparationId, setPreparationId] = useState('');
  const [dockingReviewer, setDockingReviewer] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [request, setRequest] = useState('{"workflow":"advanced","target":{},"jobs":{}}');
  const [runId, setRunId] = useState('');
  const [monitorId, setMonitorId] = useState('');
  const [report, setReport] = useState<AgentRunResult | null>(null);
  const [progress, setProgress] = useState<ResearchProgress | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { fetchResearchCapabilities().then(setCapabilities).catch(e => setError(String(e))); }, []);
  useEffect(() => {
    if (!monitorId || !token) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await fetchResearchProgress(monitorId, token);
        if (stopped) return;
        setProgress(next);
        if (next.status === 'QUEUED' || next.status === 'RUNNING') {
          timer = setTimeout(poll, 1500);
        } else {
          const result = await fetchResearchReport(monitorId, token);
          if (!stopped) { setReport(result); setBusy(false); }
        }
      } catch (e) { if (!stopped) { setError(String(e)); setBusy(false); } }
    }
    poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [monitorId, token]);
  async function start(resume = false) {
    setBusy(true); setError(''); setReport(null); setProgress(null);
    try {
      const payload = advanced ? JSON.parse(request) : { workflow: 'candidate',
        candidate_name: candidate?.name || compound, compounds: [compound],
        literature_query: query.trim() || null, remote_admet: true, docking,
        ...(docking ? { docking_preparation_id: preparationId, docking_reviewed_by: dockingReviewer } : {}),
        use_nebius_llm: llm, target: { label: 'hTERT' } };
      const result = resume ? await resumeResearch(runId, token) : await startResearch(payload, token);
      setRunId(result.run_id); setMonitorId(result.run_id);
    } catch (e) { setError(String(e)); setBusy(false); }
  }
  return <div className="h-full overflow-auto p-6 space-y-5 select-text">
    <h1 className="text-2xl font-semibold">Scientific agents</h1>
    <p>Human hTERT candidate research · A1–A7, including both A5 branches</p>
    <p>Nebius: {capabilities?.nebius ?? 'checking'} · One-candidate ADMET: {capabilities?.admet_enabled || capabilities?.compute_enabled ? 'authorized' : 'blocked'} ·
      Docking/MD: {capabilities?.compute_enabled ? 'authorized' : 'blocked'}</p>
    <label className="block">Execution token<input type="password" autoComplete="off" value={token}
      onChange={e => setToken(e.target.value)} className="block w-full bg-[#18232D] border rounded p-2" /></label>
    <CollectiveControls token={token} onStarted={id => {
      setRunId(id); setMonitorId(id); setReport(null); setProgress(null); setBusy(true); setError('');
    }} />
    <label className="block">Candidate name or SMILES<input value={compound} onChange={e => setCompound(e.target.value)}
      className="block w-full bg-[#18232D] border rounded p-2" /></label>
    <label className="block">Literature query (optional)<input value={query} onChange={e => setQuery(e.target.value)}
      className="block w-full bg-[#18232D] border rounded p-2" /></label>
    <label className="block"><input type="checkbox" checked={llm} onChange={e => setLlm(e.target.checked)} />
      Use Nebius LLM agent reviews ({capabilities?.llm?.available ? capabilities.llm.model : 'configuration required'})</label>
    <label className="block"><input type="checkbox" checked={docking} onChange={e => setDocking(e.target.checked)} />
      Request reviewed DiffDock redocking (requires prepared inputs and separate compute authorization)</label>
    {docking && <div className="space-y-2">
      <label className="block">Verified docking preparation run ID<input value={preparationId}
        onChange={e => setPreparationId(e.target.value)} className="block w-full bg-[#18232D] border rounded p-2" /></label>
      <label className="block">Scientific input reviewer<input value={dockingReviewer}
        onChange={e => setDockingReviewer(e.target.value)} className="block w-full bg-[#18232D] border rounded p-2" /></label>
    </div>}
    <p className="text-sm text-[#90A4AF]">The backend verifies target identity, resolves the actual candidate,
      runs Dockshift QSAR and profiles, and submits one molecule to Nebius ADMET when authorized.
      Biologic design and MD remain blocked until reviewed inputs and authorization exist.</p>
    <details><summary>Advanced existing runtime and discovered tool schemas</summary>
      <label><input type="checkbox" checked={advanced} onChange={e => setAdvanced(e.target.checked)} /> Use advanced JSON inputs</label>
      <textarea rows={8} value={request} onChange={e => setRequest(e.target.value)}
        className="block w-full bg-[#18232D] font-mono text-xs p-2" />
      <pre className="text-xs overflow-auto max-h-64">{JSON.stringify(capabilities, null, 2)}</pre>
    </details>
    <button disabled={busy || !token || !compound.trim()} onClick={() => start()}
      className="border border-[#59C9C0] rounded p-2 disabled:opacity-40">Start research run</button>
    <div className="flex gap-2"><input aria-label="Existing run ID" placeholder="Existing run ID" value={runId}
      onChange={e => setRunId(e.target.value)} className="bg-[#18232D] border rounded p-2 flex-1" />
      <button disabled={busy || !token || !runId} onClick={() => { setReport(null); setMonitorId(runId); }}
        className="border rounded p-2">Monitor / load</button>
      <button disabled={busy || !token || !runId} onClick={() => start(true)} className="border rounded p-2">
        Resume recorded operations</button></div>
    {progress && <section aria-label="Research progress" aria-live="polite"><h2>{progress.status} · {progress.run_id}</h2>
      {progress.detail && <p>{progress.detail}</p>}
      <ul>{progress.agents.map(a => <li key={a.agent}>{a.agent}: {a.scientific_status} · {a.detail}</li>)}</ul>
    </section>}
    {error && <p role="alert" className="text-[#E9A76A]">{error}</p>}
    {report && <AgentReport report={report} token={token} />}
  </div>;
}
