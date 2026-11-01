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
