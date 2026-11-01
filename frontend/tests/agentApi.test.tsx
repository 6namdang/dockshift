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

test('original navigation and screening components retain the team workflow', async () => {
  const { NavigationSidebar } = await import('../src/components/NavigationSidebar');
  const { ScreenView } = await import('../src/components/ScreenView');
  const { TARGET_TELOMERASE_9Q14 } = await import('../src/services/dockingService');
  const nav = renderToStaticMarkup(<NavigationSidebar activeTab="screen" onSelectTab={() => {}} noteCount={0} />);
  for (const label of ['Discover', 'Screen', 'Molecular Playground', 'Compare', 'Literature', 'Scientific Agents']) {
    assert.ok(nav.includes(label));
  }
  const screen = renderToStaticMarkup(<ScreenView protein={TARGET_TELOMERASE_9Q14} candidates={[]}
    selectedCandidateId="" onSelectCandidate={() => {}} onExploreInPlayground={() => {}}
    onRunScreening={async () => {}} isLoadingScreening={false} source="backend" />);
  assert.match(screen, /QSAR Candidate Screening Workflow/);
  assert.doesNotMatch(screen, /hERG|ADMET/);
});
