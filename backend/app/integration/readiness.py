"""Non-computational contract checks and a machine-readable readiness matrix."""

import importlib.util

from jsonschema import Draft202012Validator

from app.nebius.client import NebiusError, NebiusNotConfiguredError

from .collective import audit_plan
from .scientific_outputs import DESIGN_TOOLS, FOLD_TOOLS, MOLECULE_TOOLS


async def preflight_run(request, client, settings):
    plan = audit_plan(request)
    try:
        tools = {t.name: t for t in await client.list_tools()}
        discovery = "REACHABLE"
    except (NebiusError, NebiusNotConfiguredError):
        tools = {}
        discovery = "BLOCKED"
    checked = []
    for step in request.steps:
        local = step.job.tool == "use_prepared_structure"
        tool = tools.get(step.job.tool)
        errors = []
        if tool and tool.input_schema:
            errors = [
                {
                    "path": "/" + "/".join(str(v) for v in e.absolute_path),
                    "reason": "Native input schema mismatch",
                }
                for e in Draft202012Validator(tool.input_schema).iter_errors(step.job.arguments)
            ]
        checked.append(
            {
                "id": step.id,
                "agent": step.agent,
                "branch": step.branch,
                "tool": step.job.tool,
                "discovered": tool is not None or local,
                "schema_status": "LOCAL_REVIEW_REQUIRED"
                if local
                else "BLOCKED"
                if not tool or errors
                else "SCHEMA_VALID",
                "schema_errors": errors,
                "bindings_requiring_runtime_resolution": len(step.bindings),
                "validator_implemented": local
                or step.job.tool in {**FOLD_TOOLS, **DESIGN_TOOLS, **MOLECULE_TOOLS}
                or step.agent in ("A5a", "A6"),
                "live_output_verified": False,
            }
        )
    return {
        **plan,
        "nebius_discovery": discovery,
        "contracts": checked,
        "compute_gate_enabled": settings.agent_compute_enabled,
        "llm_credentials_present": bool(settings.anthropic_api_key)
        if settings.agent_llm_provider == "anthropic"
        else bool(settings.nebius_llm_api_key and settings.nebius_llm_model),
        "llm_gate_enabled": settings.agent_llm_enabled,
        "optional_local_parsers": {
            n: importlib.util.find_spec(n) is not None
            for n in ("gemmi", "mdtraj", "openmm", "pdbfixer")
        },
        "scientific_inputs_reviewed": False,
        "limitations": [
            "Schema checks do not qualify native output layouts or scientific inputs.",
            "Runtime resolves bindings then checks the exact native schema again.",
            "No paid computation, inference, upload or scientific precheck is performed.",
        ],
    }
