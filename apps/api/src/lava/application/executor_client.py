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
    def __init__(
        self,
        path: Path,
        key: bytes,
        job,
        deployment,
        token: str,
        fixture: str,
        mode: str = "controlled-probe",
    ):
        self.mode = mode
        self.result = None
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
        if (
            result.get("execution_id") != request.execution_id
            or result.get("mode") != self.mode
            or "error" in result
        ):
            raise ExecutionUncertain("Executor did not authorize the operation")
        return result

    def run(self, cancelled: Callable[[], bool]) -> str:
        if cancelled():
            return "cancelled"
        try:
            result = self.send("start")
            deadline = time.monotonic() + (1530 if self.mode == "fixture-build" else 30)
            cancel_sent = False
            unknown_since = None
            while time.monotonic() < deadline:
                if cancelled() and not cancel_sent:
                    result = self.send("cancel")
                    cancel_sent = True
                    deadline = min(deadline, time.monotonic() + 30)
                state = result.get("status")
                if state == "COMPLETED":
                    if self.mode == "fixture-build":
                        import re

                        if not re.fullmatch(
                            r"sha256:[0-9a-f]{64}", result.get("image_digest") or ""
                        ):
                            raise ExecutionUncertain("Executor completed without a verified image")
                        self.result = {
                            "execution_id": self.request.execution_id,
                            "image_digest": result["image_digest"],
                        }
                        return "built"
                    return "success"
                if state == "CANCELLED":
                    return "cancelled"
                if state == "FAILED":
                    return "failure"
                if state == "UNKNOWN":
                    unknown_since = unknown_since or time.monotonic()
                    if time.monotonic() - unknown_since >= 30:
                        raise ExecutionUncertain("External execution outcome is unknown")
                else:
                    unknown_since = None
                time.sleep(0.1)
                result = self.send("status")
            raise ExecutionUncertain("Executor observation deadline exceeded")
        except (OSError, ValueError) as error:
            raise ExecutionUncertain("Executor connection lost") from error
