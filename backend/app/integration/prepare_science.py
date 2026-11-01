"""No-compute preparation CLI: python -m app.integration.prepare_science."""

import asyncio
import json

from app.config import Settings
from app.literature import LiteratureSearchService
from app.literature.http import build_http_client
from app.nebius import NebiusService
from app.qsar import QsarService
from app.structural import StructuralService

from .models import RunRequest
from .service import IntegrationService


async def main():
    settings = Settings()
    async with build_http_client(settings) as http:
        service = IntegrationService(
            settings,
            LiteratureSearchService(http, settings),
            QsarService(http, settings),
            StructuralService(settings),
            NebiusService(settings),
        )
        report = await service.run(
            RunRequest(workflow="preparation", compounds=["BIBR1532"], remote_admet=False)
        )
        print(
            json.dumps(
                {
                    "run_id": report["run_id"],
                    "status": report["status"],
                    "outputs": list(report["outputs"]),
                    "expensive_compute_enabled": settings.agent_compute_enabled,
                    "scientific_jobs_submitted": 0,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
