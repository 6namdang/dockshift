# Claude reasoning with Nebius scientific computation

The existing eight-worker runtime can select Claude Messages for reasoning.
Scientific computation still uses the existing Nebius MCP adapters. QSAR,
literature, structural services, the evidence ledger and scientific approval
gates retain their behavior. No alternative scientific provider is introduced.

The account's authenticated catalog verified `claude-haiku-5-5`. It is the
default economical tool-calling model. No silent fallback occurs: an unavailable
model, unknown pricing profile, failed inference, missing key or exhausted budget
blocks further reasoning. Explicit `use_nebius_llm=true` requests preserve the
legacy Token Factory binding.

## Actual test performed

One real test executed only `A7.inspect_research`, followed by the existing typed
`conclude` contract. Claude cited the actual audit receipt hash; the structured
decision and ledger both verified. No A1–A6 execution or Nebius job occurred.

- Run: `agents-63b5cc4dd7ca48ab995dd7eb7279b78f` (ignored local artifact root).
- Two inference requests; 1,855 input tokens and 344 output tokens.
- Estimated published base-rate cost: $0.0003575, not a billing reconciliation.
- Test cap: $0.02; conservative reservation: $0.005469. No retries.

This proves one real provider/tool/receipt/structured-decision roundtrip, not a
completed eight-agent scientific workflow or validation of scientific models.

## Website configuration

A subsequent real eight-agent bounded browser demonstration is documented in
[BOUNDED_WEBSITE_DEMO.md](BOUNDED_WEBSITE_DEMO.md).

Keep the existing `ANTHROPIC_API_KEY` private in `backend/.env`; the frontend
never receives it. Configure these non-secret values when ready to enable
reasoning (the integration has not changed the local `.env`):

```dotenv
AGENT_LLM_PROVIDER=anthropic
ANTHROPIC_MODEL=claude-haiku-5-5
AGENT_LLM_ENABLED=true
ANTHROPIC_MAX_CALLS=16
ANTHROPIC_MAX_COST_USD=0.05
ANTHROPIC_MAX_INPUT_TOKENS=16000
ANTHROPIC_MAX_OUTPUT_TOKENS=512
AGENT_COMPUTE_ENABLED=false
AGENT_ADMET_ENABLED=false
```

Authenticated agent endpoints also require `STRUCTURAL_REST_ENABLED=true` and
an existing strong private `STRUCTURAL_API_TOKEN`. Enter that token only in the
website's Execution token field. This token is different from the Claude API key.

Build and launch (Node 22.12+, Python/uv):

```bash
cd ~/dockshift-integration/frontend
npm ci
npm run build
cd ../backend
uv sync --frozen
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/ui/ → Scientific Agents. The reasoning checkbox now
uses the server-configured provider and displays Claude. Enabling reasoning and
starting a research run may invoke multiple agents; this has intentionally NOT
been done in the smoke test. Scientific jobs remain blocked by their independent
gates, reviewed inputs and budgets.

For an approved future collective run, supply `use_llm: true`, optionally
`llm_provider: "anthropic"`, and a named `budget.approved_by`, positive
`budget.max_llm_calls` and `budget.max_llm_cost_usd`. The effective limits are the
smaller of the request and server limits. Defaults are zero collective calls;
preparation never constructs a reasoning provider.

Client enforcement reserves cost before each inference using token counting,
UTF-8 serialization headroom and reviewed model rates. Haiku 5.5 uses the
short-context rate because the configured input ceiling is below its 100K tier. There are
no server-side paid tools, caching requests or automatic inference retries.
These limits apply per run/provider instance, not to account-wide spending;
use Anthropic workspace spend limits for an additional account boundary.

## Developer verification

`uv run pytest tests -q` uses offline HTTP fixtures. The optional
`uv run python -m app.integration.claude_smoke` command is a dry-run; `--execute`
submits a new paid two-message test and should not be repeated automatically.

Provider modules: `anthropic_llm.py`, `llm_provider.py`; runtime entry:
`runtime.py`; secret redaction: `privacy.py`. Native Claude content/tool IDs are
preserved across tool results. Each outgoing call and conclusion is validated
against the existing tool/decision contracts. No new SDK dependency is needed.

Primary references: [Haiku 5.5 model/pricing](https://platform.claude.com/docs/en/models/haiku-5-5/overview),
[tool-call lifecycle](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls),
[token counting](https://platform.claude.com/docs/en/api/messages/count_tokens).
