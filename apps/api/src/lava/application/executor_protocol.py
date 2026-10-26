"""Authenticated executor envelopes; transport must also enforce local peer permissions.

Verification authenticates an envelope only. Callers must transactionally validate
its job lease and persist its nonce before authorizing any external execution.
"""

import hashlib
import hmac
import json
import re
import time
from dataclasses import asdict, dataclass
from uuid import UUID


@dataclass(frozen=True)
class ExecutorRequest:
    execution_id: str
    job_id: str
    deployment_id: str
    claim_generation: int
    source_commit: str
    configuration_revision: int
    fixture: str
    operation: str
    nonce: str
    expires_at: int
    version: int = 1

    def validate(self, now: float) -> None:
        if self.version != 1:
            raise ValueError("Unsupported executor protocol")
        for identifier in (self.execution_id, self.job_id, self.deployment_id):
            if str(UUID(identifier)) != identifier:
                raise ValueError("Invalid identity")
        if self.operation not in {"start", "status", "cancel", "result", "cleanup"}:
            raise ValueError("Invalid operation")
        if self.fixture not in {"python", "node", "go"}:
            raise ValueError("Unapproved fixture")
        if not re.fullmatch(r"[0-9a-f]{40}", self.source_commit):
            raise ValueError("Invalid source")
        if not re.fullmatch(r"[0-9a-f]{64}", self.nonce):
            raise ValueError("Invalid nonce")
        if self.claim_generation < 1 or self.configuration_revision < 1:
            raise ValueError("Invalid revision")
        if not now < self.expires_at <= now + 60:
            raise ValueError("Expired or excessive authorization lifetime")


def _payload(request: ExecutorRequest) -> bytes:
    return json.dumps(asdict(request), sort_keys=True, separators=(",", ":")).encode()


def sign(request: ExecutorRequest, key: bytes) -> str:
    if len(key) < 32:
        raise ValueError("Executor key requires at least 256 bits")
    return hmac.new(key, b"lava-executor-v1\0" + _payload(request), hashlib.sha256).hexdigest()


def authenticate(
    request: ExecutorRequest, signature: str, key: bytes, *, now: float | None = None
) -> None:
    if not hmac.compare_digest(sign(request, key), signature):
        raise PermissionError("Invalid executor authentication")
    request.validate(time.time() if now is None else now)
