"""Durable provider acceptance checkpoints, without provider or HTTP dependencies."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Awaitable, Callable

from .models import AigcJob
from .provider_errors import ProviderSubmissionRejected
from ..storage.repos.aigc_execution_repo import AigcExecutionRepository


def execution_command(job: AigcJob) -> dict:
    return job.model_dump(mode="json", include={
        "id", "canvas_id", "node_id", "capability", "provider_id", "model_id",
        "inputs", "parameters", "created_at",
    })


class ProviderExecution:
    def __init__(self, repository: AigcExecutionRepository, job_id: str, token: str, *, read_only: bool):
        self.repository = repository
        self.job_id = job_id
        self.token = token
        self.read_only = read_only

    def accepted(self, slot: str, adapter: str) -> str | None:
        return self.repository.prepare_provider_task(
            self.job_id, self.token, slot, adapter, read_only=self.read_only, reserve=False,
        )

    def check_active(self) -> None:
        self.repository.renew_job_attempt(self.job_id, self.token)

    async def submit(self, slot: str, adapter: str, submit: Callable[[], Awaitable[str]]) -> str:
        remote_id = self.repository.prepare_provider_task(
            self.job_id, self.token, slot, adapter, read_only=self.read_only,
        )
        if remote_id is not None:
            return remote_id
        try:
            remote_id = await submit()
        except ProviderSubmissionRejected as exc:
            self.repository.reject_provider_task(self.job_id, self.token, slot, str(exc))
            raise
        self.repository.accept_provider_task(self.job_id, self.token, slot, remote_id)
        return remote_id

    @asynccontextmanager
    async def keepalive(self):
        self.check_active()
        async def renew():
            while True:
                await asyncio.sleep(30)
                self.repository.renew_job_attempt(self.job_id, self.token)

        renewal = asyncio.create_task(renew())
        try:
            yield
            # Do not persist results under a lost lease after a long provider call.
            if renewal.done():
                renewal.result()
            self.repository.renew_job_attempt(self.job_id, self.token)
        finally:
            renewal.cancel()
            with suppress(asyncio.CancelledError):
                await renewal
