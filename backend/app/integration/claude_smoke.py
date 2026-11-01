"""ONE bounded Claude/A7 tool-use test. No other agent or scientific job runs.

Use --execute once after explicit approval. No automatic retries or fallbacks.
The existing A7 tool inspects an honest empty scientific ledger, then Claude
submits the existing structured conclude contract citing real receipt hashes.
"""

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from types import SimpleNamespace

from app.config import BACKEND_DIR, Settings

from .anthropic_llm import AnthropicLLMProvider
from .models import RunRequest
from .privacy import Redactor
from .runtime import new_run_id
from .scienceclaw.contracts import AgentEvent, ArtifactRef, WorkerState
from .scienceclaw.runtime.engine import CONCLUDE, Decision, function
from .tools import DockshiftTools


async def smoke(settings):
    # This ephemeral override authorizes only the explicit two-message smoke test.
    # No environment files or persistent compute/inference gates are changed.
    settings = settings.model_copy(
        update={
            "agent_llm_enabled": True,
            "agent_compute_enabled": False,
            "agent_admet_enabled": False,
            "anthropic_max_calls": 2,
            "anthropic_max_cost_usd": 0.02,
            "anthropic_max_input_tokens": 16000,
            "anthropic_max_output_tokens": 512,
        }
    )
    provider = AnthropicLLMProvider(settings, max_calls=2, max_cost_usd=0.02)
    root = settings.agent_artifact_root
    root = root if root.is_absolute() else BACKEND_DIR / root
    run_id = new_run_id()
    out = root / run_id
    out.mkdir(parents=True, exist_ok=False)
    redact = Redactor(settings)
    science = DockshiftTools(
        settings,
        RunRequest(),
        out,
        run_id,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
    )
    science.observations = {
        a: {
            "status": "BLOCKED",
            "artifacts": [],
            "detail": "Not executed in the Claude smoke test.",
        }
        for a in ("A1", "A2", "A3", "A4", "A5a", "A5b", "A6")
    }

    def save(name, data):
        with (out / name).open("x") as handle:
            json.dump(redact(data), handle, indent=2, allow_nan=False)

    messages = [
        {
            "role": "system",
            "content": (
                "You are A7, the independent scientific evidence auditor. This is "
                "a provider integration test, not a research experiment. Call insp"
                "ect_research once with {}. Do not invent results or request compu"
                "tation."
            ),
        },
        {
            "role": "user",
            "content": "Inspect the current local evidence ledger using the supplied tool.",
        },
    ]
    tools = [
        function(
            "inspect_research",
            (
                "Inspect the real local ledger and report incomplete agents. No sc"
                "ientific computation."
            ),
        )
    ]
    save("claude_first_request.json", {"messages": messages, "tools": tools})
    first = await asyncio.to_thread(provider.chat, messages, tools)
    save("claude_first_response.json", first)
    call = first["message"]["tool_calls"][0]["function"]
    if call["name"] != "inspect_research" or call["arguments"] != {}:
        raise ValueError("Claude did not request the permitted existing A7 tool")
    receipt = await science.execute("A7")
    if receipt["status"] != "SUCCEEDED":
        raise ValueError("Local A7 audit failed")
    refs = receipt["artifacts"]
    if not all(ArtifactRef(**a).verify() for a in refs):
        raise ValueError("Receipt hash verification failed")
    tool_result = {
        **receipt,
        "cite_these_hashes": refs,
        "scientific_scope": (
            "Only an evidence audit ran. All seven scientific workers were NOT"
            " RUN; no binding, docking or MD result exists."
        ),
    }
    messages += [
        first["message"],
        {"role": "tool", "tool_name": "inspect_research", "content": json.dumps(tool_result)},
        {
            "role": "user",
            "content": (
                "Call conclude now. Complete the audit, cite one exact receipt SHA"
                "-256, and state that scientific execution has not occurred. No re"
                'design: redesign_target="none", allowed_fragments=[].'
            ),
        },
    ]
    save("claude_conclude_request.json", {"messages": messages, "tools": [CONCLUDE]})
    final = await asyncio.to_thread(provider.chat, messages, [CONCLUDE])
    save("claude_conclude_response.json", final)
    call = final["message"]["tool_calls"][0]["function"]
    if call["name"] != "conclude":
        raise ValueError("Claude did not submit a structured conclusion")
    decision = Decision.parse(call["arguments"], {a["sha256"] for a in refs})
    if decision.redesign_target != "none":
        raise ValueError("Smoke test cannot request redesign")
    save("claude_decision.json", asdict(decision))
    science.ledger.append(
        AgentEvent(
            run_id=run_id,
            agent="A7",
            event_type="CLAUDE_SMOKE_DECISION",
            status=WorkerState.SUCCEEDED,
            outputs=[ArtifactRef.of(out / "claude_decision.json", "llm_decision")],
            input_artifact_hashes=decision.evidence_hashes,
            note=(
                "Real Claude tool-calling smoke test only; no full research workfl"
                "ow or scientific jobs."
            ),
        )
    )
    input_tokens = sum(u.get("input_tokens", 0) for u in provider.usage)
    output_tokens = sum(u.get("output_tokens", 0) for u in provider.usage)
    result = {
        "run_id": run_id,
        "status": "SUCCEEDED",
        "provider": "anthropic",
        "model": provider.model,
        "inference_requests": provider.calls,
        "max_cost_usd": "0.02",
        "reserved_cost_usd": str(provider.reserved_usd),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd_base_rates": (input_tokens * 0.10 + output_tokens * 0.50) / 1_000_000
        if provider.model == "claude-haiku-5-5"
        else None,
        "existing_agent_tool": "A7.inspect_research",
        "structured_decision_valid": True,
        "ledger_verified": science.ledger.verify()[0],
        "scientific_jobs_submitted": 0,
        "full_eight_agent_workflow_executed": False,
        "report_path": str(out / "claude_smoke_report.json"),
    }
    save("claude_smoke_report.json", result)
    save(
        "manifest.json",
        {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()},
    )
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(

                "Not executed. --execute authorizes one A7 test, at most 2 inferen"
                "ce requests and $0.02; no retries."

        )
        return
    print(json.dumps(await smoke(Settings()), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
