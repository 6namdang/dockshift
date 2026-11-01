"""Executable final-run entry point. Preflight is the default; execution is opt-in."""

import argparse
import asyncio
import json
from pathlib import Path

from app.config import Settings
from app.literature import LiteratureSearchService
from app.literature.http import build_http_client
from app.nebius import NebiusService
from app.qsar import QsarService
from app.structural import StructuralService

from .models import RunRequest
from .readiness import preflight_run
from .service import IntegrationService


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Requires separate reviewed budget and disabled-by-default server gates",
    )
    args = parser.parse_args()
    request = RunRequest.model_validate_json(args.protocol.read_text())
    if request.workflow != "collective":
        raise ValueError("Final protocol must explicitly select collective workflow")
    settings = Settings()
    nebius = NebiusService(settings)
    if not args.execute:
        print(json.dumps(await preflight_run(request, nebius.client, settings), indent=2))
        return
    if (
        not settings.agent_compute_enabled
        or request.budget.max_submissions <= 0
        or not request.budget.approved_by
    ):
        raise SystemExit(
            "BLOCKED: separate compute authorization and a reviewed submission budget are required."
        )
    async with build_http_client(settings) as http:
        service = IntegrationService(
            settings,
            LiteratureSearchService(http, settings),
            QsarService(http, settings),
            StructuralService(settings),
            nebius,
        )
        report = await service.run(request)
        print(json.dumps({"run_id": report["run_id"], "status": report["status"]}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
