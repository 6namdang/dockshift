"""One process-wide admission budget for structural work."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache


class StructuralAdmissionController:
    """A loop-independent asynchronous facade over one bounded process semaphore."""

    def __init__(self, max_jobs: int) -> None:
        self.max_jobs = max_jobs
        self._semaphore = threading.BoundedSemaphore(max_jobs)

    @asynccontextmanager
    async def admit(self) -> AsyncIterator[None]:
        acquired = False
        try:
            while not acquired:
                acquired = self._semaphore.acquire(blocking=False)
                if not acquired:
                    await asyncio.sleep(0.01)
            yield
        finally:
            if acquired:
                self._semaphore.release()


@cache
def get_structural_admission_controller(max_jobs: int) -> StructuralAdmissionController:
    """Return the shared controller for the configured in-process budget."""
    return StructuralAdmissionController(max_jobs)
