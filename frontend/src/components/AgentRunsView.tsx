import React, { useEffect, useState } from 'react';
import {
  AgentCapabilities, AgentRunResult, fetchAgentCapabilities, fetchAgentReport,
  runScientificAgents,
} from '../dockshiftApi';

export function AgentReport({ report }: { report: AgentRunResult }) {
  return <section aria-label="Agent run report" className="space-y-4">
    <h2 className="text-lg font-semibold">Run {report.status}</h2>
    <p className="text-sm text-[#90A4AF] break-all">{report.run_id}</p>
    <p>Ledger: {report.ledger_integrity.verified ? 'verified' : 'integrity failure'} ·
      LLM workers invoked: {report.llm_agents_invoked}/8 · Scientific review: {report.scientific_review}</p>
    <div className="overflow-x-auto"><table className="w-full text-left text-sm">
      <thead><tr>{['Agent', 'Science', 'Agent review', 'Evidence / blocker'].map(h =>
        <th key={h} className="p-2 border-b border-[#202F3C]">{h}</th>)}</tr></thead>
      <tbody>{report.agents.map(a => <tr key={a.agent}>
        <td className="p-2">{a.agent} · {a.role}</td>
        <td className="p-2">{a.scientific_status}</td>
        <td className="p-2">{a.agent_status}</td>
        <td className="p-2">{a.detail}</td>
      </tr>)}</tbody>
    </table></div>
    <h3 className="font-semibold">Computed evidence</h3>
    {report.computational_evidence.length === 0
      ? <p>No computed metrics were recorded.</p>
      : <ul>{report.computational_evidence.map((m, i) =>
        <li key={i}>{m.agent}: {m.metric} = {m.value} {m.unit} · {m.method}</li>)}</ul>}
    <p className="text-sm text-[#90A4AF]">{report.separation_statement}</p>
    <button className="border rounded p-2" onClick={() => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `${report.run_id}.json`; anchor.click();
      URL.revokeObjectURL(url);
    }}>Download evidence report</button>
  </section>;
}

export function AgentRunsView() {
  const [capabilities, setCapabilities] = useState<AgentCapabilities | null>(null);
  const [token, setToken] = useState('');
  const [request, setRequest] = useState(JSON.stringify({
    target: { label: 'hTERT', species: 'Homo sapiens', verified: false },
    compounds: [], use_local_llm: false, jobs: {},
  }, null, 2));
  const [runId, setRunId] = useState('');
  const [report, setReport] = useState<AgentRunResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { fetchAgentCapabilities().then(setCapabilities).catch(e => setError(String(e))); }, []);
  async function execute(load: boolean) {
    setBusy(true); setError('');
    try {
      const result = load ? await fetchAgentReport(runId, token)
        : await runScientificAgents(JSON.parse(request), token);
      setReport(result); setRunId(result.run_id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  return <div className="h-full overflow-auto p-6 space-y-6 select-text">
    <h1 className="text-2xl font-semibold">Scientific agents</h1>
    <p className="text-[#90A4AF]">A1–A7 evidence workflow, including both A5 branches.
      Each tool and agent review reports its own execution status.</p>
    <p>Nebius: {capabilities?.nebius ?? 'checking'} · Scientific compute:
      {capabilities?.compute_enabled ? ' enabled' : ' disabled'}</p>
    <details><summary>Available scientific models and input schemas</summary>
      <pre className="text-xs overflow-auto p-3">{JSON.stringify(capabilities, null, 2)}</pre>
    </details>
    <label className="block">Execution token
      <input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)}
        className="block border border-[#202F3C] bg-[#18232D] p-2 rounded w-full" />
    </label>
    <label className="block">Reviewed run inputs (JSON)
      <textarea rows={12} value={request} onChange={e => setRequest(e.target.value)}
        spellCheck={false} className="block w-full font-mono text-sm bg-[#18232D] border border-[#202F3C] p-3 rounded" />
    </label>
    <p className="text-sm text-[#90A4AF]">Supply verified target identifiers and their source.
      Missing inputs produce blockers. A local LLM is optional; tool execution alone does
      not count as LLM agency. Remote model calls require the server compute setting.</p>
    <button disabled={busy || !token} onClick={() => execute(false)}
      className="border border-[#59C9C0] rounded p-2 disabled:opacity-40">
      {busy ? 'Working…' : 'Run reviewed workflow'}
    </button>
    <div className="flex gap-2">
      <input aria-label="Existing run ID" placeholder="Existing run ID" value={runId}
        onChange={e => setRunId(e.target.value)} className="bg-[#18232D] border rounded p-2 flex-1" />
      <button disabled={busy || !token || !runId} className="border rounded p-2 disabled:opacity-40"
        onClick={() => execute(true)}>Load report</button>
    </div>
    {error && <p role="alert" className="text-[#E9A76A]">{error}</p>}
    {report && <AgentReport report={report} />}
  </div>;
}
