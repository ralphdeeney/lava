"""Worker-side authenticated client; holds no process or Docker authority."""

import secrets
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid5

from lava.application.executor_protocol import ExecutorRequest


class ExecutionUncertain(RuntimeError):
    pass


class SocketExecutor:
    def __init__(self, path: Path, key: bytes, job, deployment, token: str, fixture: str):
        self.path, self.key = path, key
        self.request = ExecutorRequest(
            str(uuid5(UUID(job.id), str(job.lease_generation))),
            job.id,
            deployment.id,
            job.lease_generation,
            deployment.source_commit_sha,
            deployment.configuration_revision,
            fixture,
            "start",
            secrets.token_hex(32),
            int(time.time()) + 30,
            lease_owner=job.lease_owner,
            lease_token=token,
        )

    def send(self, operation: str) -> dict:
        from lava.executor import exchange

        request = replace(
            self.request,
            operation=operation,
            nonce=secrets.token_hex(32),
            expires_at=int(time.time()) + 30,
        )
        result = exchange(self.path, self.key, request)
        if result.get("execution_id") != request.execution_id or "error" in result:
            raise ExecutionUncertain("Executor did not authorize the operation")
        return result

    def run(self, cancelled: Callable[[], bool]) -> str:
        if cancelled():
            return "cancelled"
        try:
            result = self.send("start")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if cancelled():
                    result = self.send("cancel")
                state = result.get("status")
                if state == "COMPLETED":
                    return "success"
                if state == "CANCELLED":
                    return "cancelled"
                if state == "FAILED":
                    return "failure"
                if state == "UNKNOWN":
                    raise ExecutionUncertain("External execution outcome is unknown")
                time.sleep(0.1)
                result = self.send("status")
            raise ExecutionUncertain("Executor observation deadline exceeded")
        except (OSError, ValueError) as error:
            raise ExecutionUncertain("Executor connection lost") from error
