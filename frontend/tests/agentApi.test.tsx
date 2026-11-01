import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { runScientificAgents, fetchAgentReport, AgentRunResult } from '../src/dockshiftApi';
import { AgentReport } from '../src/components/AgentRunsView';

const blocked: AgentRunResult = {
  run_id: 'agents-test', status: 'BLOCKED', llm_agents_invoked: 0,
  ledger_integrity: { verified: true, error: null }, scientific_review: 'REQUIRED',
  separation_statement: 'Computational hypotheses require experiments.',
  computational_evidence: [], agents: [{ agent: 'A6', role: 'Dynamics',
    agent_status: 'BLOCKED', scientific_status: 'BLOCKED',
    detail: 'MD inputs missing', llm_inference_calls: 0 }],
};

test('runtime API uses authenticated body and report path without putting tokens in URLs', async () => {
  const original = globalThis.fetch;
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify(blocked));
  };
  try {
    assert.equal((await runScientificAgents({ compounds: [] }, 'test-token')).status, 'BLOCKED');
    await fetchAgentReport('agents/test', 'test-token');
    assert.equal(calls[0].url, '/api/v1/agents/runs');
    assert.equal(calls[0].init?.method, 'POST');
    assert.equal(new Headers(calls[0].init?.headers).get('Authorization'), 'Bearer test-token');
    assert.equal(calls[0].init?.body, '{"compounds":[]}');
    assert.equal(calls[1].url, '/api/v1/agents/runs/agents%2Ftest');
    assert.ok(calls.every(c => !c.url.includes('test-token')));
  } finally { globalThis.fetch = original; }
});

test('blocked report shows separate science and review states without invented metrics', () => {
  const html = renderToStaticMarkup(<AgentReport report={blocked} />);
  assert.match(html, /Run BLOCKED/);
  assert.match(html, /MD inputs missing/);
  assert.match(html, /No computed metrics were recorded/);
  assert.match(html, /Scientific review: REQUIRED/);
  assert.doesNotMatch(html, /0\.0|SUCCEEDED/);
});

test('backend errors remain errors and never fall back to demo results', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Token required' }), { status: 401 });
  try { await assert.rejects(fetchAgentReport('agents-test', ''), /Token required/); }
  finally { globalThis.fetch = original; }
});

test('managed research starts, polls and resumes only through integration endpoints', async () => {
  const api = await import('../src/integration/researchApi');
  const original = globalThis.fetch;
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ run_id: 'agents-fixture', status: 'QUEUED', agents: [] }));
  };
  try {
    await api.startResearch({ workflow: 'candidate', compounds: ['CCO'] }, 'test-token');
    await api.fetchResearchProgress('agents-fixture', 'test-token');
    await api.resumeResearch('agents-fixture', 'test-token');
    assert.deepEqual(calls.map(c => c.url), ['/api/v1/agents/research',
      '/api/v1/agents/runs/agents-fixture/progress', '/api/v1/agents/runs/agents-fixture/resume']);
    assert.equal(calls[0].init?.method, 'POST');
    assert.equal(calls[2].init?.method, 'POST');
    assert.ok(calls.every(c => new Headers(c.init?.headers).get('Authorization') === 'Bearer test-token'));
  } finally { globalThis.fetch = original; }
});

test('managed research renders native values and distinguishes candidate completion from full science', async () => {
  const { AgentReport } = await import('../src/components/AgentRunsView');
  const report = { ...blocked, candidate_screening_status: 'COMPLETED', outputs: {
    admet: { model_version: 'test-version', validation: 'Artifact hash and identity verified',
      endpoints: [{ endpoint: 'hERG', value: 0.2, units: '-', species: 'human', task_type: 'classification' }],
      artifacts: [], limitations: ['Test fixture'] },
  } };
  const html = renderToStaticMarkup(<AgentReport report={report} />);
  assert.match(html, /Candidate screen: COMPLETED/);
  assert.match(html, /Full scientific workflow: BLOCKED/);
  assert.match(html, /hERG/);
  assert.match(html, /0\.2/);
  assert.match(html, /Target-independent model predictions/);
});

test('research requests never fall back to educational candidate or literature data', async () => {
  const api = await import('../src/integration/researchApi');
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Execution disabled' }), { status: 503 });
  try { await assert.rejects(api.startResearch({ workflow: 'candidate' }, 'test-token'), /Execution disabled/); }
  finally { globalThis.fetch = original; }
});

test('navigation exposes the four workflow tabs', async () => {
  const { NavigationSidebar } = await import('../src/components/NavigationSidebar');
  const nav = renderToStaticMarkup(
    <NavigationSidebar activeTab="pipeline" onSelectTab={() => {}} />
  );
  for (const label of ['Pipeline', 'Structure', 'Literature', 'Agents']) {
    assert.ok(nav.includes(label), `missing tab: ${label}`);
  }
  // The exploratory tabs were folded into the pipeline; they must not come back.
  for (const gone of ['Discover', 'Screen', 'Compare', 'Molecular Playground']) {
    assert.ok(!nav.includes(gone), `removed tab still rendered: ${gone}`);
  }
});

test('collective controls expose non-computational preflight and explicit zero budget', async () => {
  const { CollectiveControls } = await import('../src/integration/CollectiveWorkflow');
  const html = renderToStaticMarkup(<CollectiveControls token="" onStarted={() => {}} />);
  assert.match(html, /small molecule and protein biologic branches/);
  assert.match(html, /Check prerequisites and Nebius contracts/);
  assert.match(html, /max_submissions/);
  assert.match(html, /Missing reasoning-provider access stays blocked/);
});

test('collective preflight calls only its authenticated read-only endpoint', async () => {
  const { preflightResearch } = await import('../src/integration/researchApi');
  const original = globalThis.fetch;
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ submission_performed: false, status: 'BLOCKED' }));
  };
  try {
    await preflightResearch({ workflow: 'collective', budget: { max_submissions: 0 } }, 'test-token');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/v1/agents/preflight');
    assert.equal(new Headers(calls[0].init?.headers).get('Authorization'), 'Bearer test-token');
    assert.ok(!calls[0].url.includes('test-token'));
  } finally { globalThis.fetch = original; }
});

test('collective report separates branch blockers and preserves native model confidence', async () => {
  const { CollectiveReport } = await import('../src/integration/CollectiveWorkflow');
  const html = renderToStaticMarkup(<CollectiveReport runId="agents-fixture" token="" output={{
    branches: { small_molecule: { status: 'BLOCKED', missing_agents: ['A6'], scientific_acceptance: 'REVIEW_REQUIRED' },
      biologic: { status: 'BLOCKED', missing_agents: ['A4', 'A5b', 'A6'], scientific_acceptance: 'REVIEW_REQUIRED' } },
    steps: { complex: { agent: 'A5b', branch: 'biologic', status: 'SUCCEEDED', tool: 'boltz2_predict_native',
      validation: { kind: 'complex', model_id: 'boltz2', model_version: 'SYNTHETIC-TEST-ONLY', native_confidence: { iptm: [.8] },
        limitations: ['Synthetic fixture; no binding claim'] } } },
  }} />);
  assert.match(html, /Small molecule: BLOCKED/);
  assert.match(html, /Protein biologic: BLOCKED/);
  assert.match(html, /iptm/);
  assert.match(html, /Synthetic fixture; no binding claim/);
  assert.doesNotMatch(html, /affinity =|pIC50 =|converged/);
});

test('bounded demonstration starts only through its authenticated endpoint', async () => {
  const { startDemonstration } = await import('../src/integration/researchApi');
  const original = globalThis.fetch;
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ run_id: 'agents-fixture', status: 'QUEUED' })); };
  try {
    await startDemonstration('test-token');
    assert.equal(calls[0].url, '/api/v1/agents/demonstration');
    assert.equal(calls[0].init?.method, 'POST');
    assert.equal(new Headers(calls[0].init?.headers).get('Authorization'), 'Bearer test-token');
  } finally { globalThis.fetch = original; }
});
