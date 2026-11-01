import React, { useState } from 'react';
import { downloadResearchArtifact, preflightResearch, startResearch, ScientificArtifact } from './researchApi';

export interface CollectiveStepReport {
  agent?: string; branch?: string; tool?: string; status: string; code?: string; detail?: string;
  operation_id?: string; artifacts?: ScientificArtifact[];
  validation?: { kind?: string; model_id?: string; model_version?: string;
    native_confidence?: Record<string, unknown>; limitations?: string[]; [key: string]: unknown };
}
export interface CollectiveOutput {
  branches: Record<string, { status: string; missing_agents: string[]; scientific_acceptance: string }>;
  steps: Record<string, CollectiveStepReport>;
}

export function CollectiveControls({ token, onStarted }: {
  token: string; onStarted: (id: string) => void;
}) {
  const [protocol, setProtocol] = useState(JSON.stringify({ workflow: 'collective',
    branches: ['small_molecule', 'biologic'], target: { label: 'hTERT', accession: 'O14746' },
    use_nebius_llm: false, budget: { max_submissions: 0 }, steps: [],
  }, null, 2));
  const [preflight, setPreflight] = useState<unknown>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(execute: boolean) {
    setBusy(true); setError('');
    try {
      const request = JSON.parse(protocol);
      if (request.workflow !== 'collective') throw new Error('Select the collective workflow in the reviewed protocol.');
      if (execute) {
        const result = await startResearch(request, token); onStarted(result.run_id);
      } else setPreflight(await preflightResearch(request, token));
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  return <details className="border rounded p-3 space-y-3">
    <summary>Collective research · small molecule and protein biologic branches</summary>
    <p>Load the reviewed final-run protocol. Each stage names its Nebius model, exact inputs,
      scientific acceptance checks and verified upstream artifacts. A zero submission budget submits no jobs.</p>
    <label className="block">Reviewed collective protocol
      <textarea aria-label="Reviewed collective protocol" rows={12} value={protocol}
        onChange={e => { setProtocol(e.target.value); setPreflight(null); }}
        className="block w-full bg-[#18232D] font-mono text-xs p-2" />
    </label>
    <div className="flex gap-2">
      <button disabled={busy || !token} onClick={() => submit(false)} className="border rounded p-2">
        Check prerequisites and Nebius contracts</button>
      <button disabled={busy || !token} onClick={() => submit(true)} className="border rounded p-2">
        Start reviewed collective run</button>
    </div>
    <p>Contract checks perform no scientific computation. Execution still requires server authorization,
      a named reviewer, a submission budget and valid scientific inputs. Missing Token Factory access stays blocked.</p>
    {preflight != null && <pre aria-label="Collective preflight" className="text-xs overflow-auto max-h-96">{JSON.stringify(preflight, null, 2)}</pre>}
    {error && <p role="alert">{error}</p>}
  </details>;
}

export function CollectiveReport({ output, runId, token }: {
  output: CollectiveOutput; runId: string; token: string;
}) {
  const [error, setError] = useState('');
  async function download(artifact: ScientificArtifact) {
    try {
      const blob = await downloadResearchArtifact(runId, artifact.filename, token);
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())))
        .map(v => v.toString(16).padStart(2, '0')).join('');
      if (digest !== artifact.sha256) throw new Error('Artifact SHA-256 verification failed.');
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = artifact.filename; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(String(e)); }
  }
  return <section aria-label="Collective scientific branches" className="space-y-3">
    <h3>Collective scientific evidence</h3>
    {Object.entries(output.branches).map(([name, branch]) => <p key={name}>
      {name === 'small_molecule' ? 'Small molecule' : 'Protein biologic'}: {branch.status} · {branch.scientific_acceptance}
      {branch.missing_agents.length > 0 && ` · Missing stages: ${branch.missing_agents.join(', ')}`}
    </p>)}
    {Object.entries(output.steps).map(([id, step]) => <details className="border rounded p-3" key={id}>
      <summary>{step.agent} · {id} · {step.branch} · {step.status}</summary>
      <p>{step.tool} {step.operation_id && `· Operation ${step.operation_id}`}</p>
      <p>{step.code} {step.detail}</p>
      {step.validation && <>
        <p>Native model: {step.validation.model_id} · Version: {step.validation.model_version}</p>
        <pre className="text-xs overflow-auto max-h-96">{JSON.stringify(step.validation, null, 2)}</pre>
        <ul>{step.validation.limitations?.map((item, i) => <li key={i}>{item}</li>)}</ul>
      </>}
      {step.artifacts?.map(a => <div key={a.filename} className="break-all text-xs">
        <p>{a.filename} · SHA-256 {a.sha256} · {a.size_bytes} bytes</p>
        <button disabled={!token} onClick={() => download(a)} className="border rounded p-2">Download and verify artifact</button>
      </div>)}
    </details>)}
    {error && <p role="alert">{error}</p>}
  </section>;
}
