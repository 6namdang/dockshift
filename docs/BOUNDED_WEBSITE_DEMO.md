# Bounded eight-agent website demonstration

A real browser demonstration used Claude Haiku 5.5 for reasoning, existing
Dockshift local QSAR/chemistry tools, live UniProt/RCSB records and read-only
Nebius model discovery. No remote scientific models were executed.

The website is served by a dedicated loopback-only demo process on
`http://127.0.0.1:8767/ui/`. The existing port-8000 process was left untouched.
The build is under `/private/tmp/dockshift-bounded-demo-build-20261101`;
repository build artifacts and the local `.env` were not rewritten by this demo.

## Verified outcome

- Source run: `agents-3f311e12105f48f889f805bcf16ed79d`.
- Final continuation: `agents-21ae35c92b5944bba4d386a79dd83ddb`.
- **All eight agents performed actual Claude inference and completed valid structured decisions.**
- **17 total requests**, including one rejected A6 tool response; ceiling **24**.
- Conservative cumulative cost reservation **$0.0160397**, ceiling **$0.10**.
- Fourteen evidence handoffs were delivered, SHA-256 verified and acknowledged.
- Both scientific ledgers and execution-trace hash chains verified.
- Browser rendered the report without JavaScript errors; an artifact download
  was independently verified against its recorded SHA-256.
- Nebius access consisted solely of `list_tools` and `get_model_schema` reads.
- **Zero scientific submissions. Overall scientific status: BLOCKED.**

| Agent | Actual LLM requests | Tool work / scientific scope |
|---|---:|---|
| A1 | 2 | Live human hTERT identity and 9Q14/55C primary sources verified |
| A2 | 2 | Deposited structure audited; no structure prediction |
| A3 | 2 | Existing local QSAR/profile and chemistry checks; ADMET not run |
| A4 | 2 | Real Nebius design contracts inspected; binder generation blocked |
| A5a | 2 | DiffDock request and reference inputs prepared; docking blocked |
| A5b | 2 | Real complex-prediction contracts inspected; prediction blocked |
| A6 | 3 | One invalid tool response, then two valid continuation calls; MD prerequisite/protocol audit only |
| A7 | 2 | Independent artifact/ledger/completeness audit; no efficacy claim |

The existing QSAR returned BIBR1532 predicted pIC50 **5.83**, with an exact
training-set match. This is a model prediction, not a new assay or independent
validation. The deposited hTERT chain still has unresolved regions; no repaired,
parameterized MD system or simulation results were invented.

A6 originally added `redesign_target` to a tool that accepts only `{}`. Validation
rejected it before execution, and the provider stopped subsequent inference.
The first run is retained unchanged. Claude strict tool-schema mode was enabled,
and only A6/A7 continued using verified earlier artifacts. The original 13
requests and cost reservations were carried forward, not reset. One invalid
response's detailed native usage was not retained by the previous validator;
its request and conservative reservation remain counted. Known usage for the
other 16 responses was 42,586 input and 3,404 output tokens (published-base-rate
estimate $0.0059606, excluding that invalid response). Reservations are not bills.

## Inspect locally

Open Scientific Agents, enter the private demo execution token from
`backend/.dockshift-agent-runs/demo-session-76ea4f62f13d45af9c2032b2d4a71337/browser_connection.json`,
and monitor/load the final run ID above. This fresh demo-only token is different
from API keys, is stored with mode 0600, and is never included in Git or reports.
The same ignored session directory contains `website-demonstration.png`,
`browser-verification.json` and `independent-verification.json`.

The one-shot server rejects further run submissions. All scientific compute,
ADMET, unrelated write routes and non-schema Nebius calls are disabled in that
process. Do not restart a fresh paid demonstration without a new budget approval.
The launcher is `python -m app.integration.demo_server --frontend-dir PATH`;
`--continue-run ID` restores verified completed workers and their original spend
counters. It does not authorize an unlimited new run. Ordinary Dockshift startup
and the existing application remain separate from this dedicated demo mode.

Current code adds a demo API/button, readable per-agent inference counts and
structured-decision status, conservative request/cost limits, and hash-verified
continuation. Tests use explicitly synthetic fixtures; the run IDs above refer
to the actual browser execution.
