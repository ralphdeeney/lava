"""Standalone PostgreSQL deployment worker with a deterministic simulated executor."""

from __future__ import annotations

import hashlib
import secrets
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from lava.application.deployments import DeploymentService
from lava.db.base import Deployment, DeploymentJob

log = structlog.get_logger()


class LeaseLost(RuntimeError):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SimulatedExecutor:
    def __init__(self, outcome: str = "success"):
        self.outcome = outcome

    def run(self, cancelled: Callable[[], bool]) -> str:
        if cancelled():
            return "cancelled"
        if self.outcome == "timeout":
            time.sleep(0.01)
            return "retryable_failure"
        if self.outcome == "failure":
            return "failure"
        return "success"


class DeploymentWorker:
    def __init__(
        self, session: Session, worker_id: str, lease_seconds: int = 60, max_attempts: int = 3
    ):
        self.session = session
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def claim(self) -> tuple[DeploymentJob, str] | None:
        now = datetime.now(UTC)
        query = (
            select(DeploymentJob)
            .where(
                or_(
                    (
                        DeploymentJob.status.in_(["queued", "retry_wait"])
                        & (DeploymentJob.available_at <= now)
                    ),
                    (DeploymentJob.status == "running") & (DeploymentJob.leased_until < now),
                )
            )
            .order_by(DeploymentJob.priority.desc(), DeploymentJob.available_at, DeploymentJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = self.session.scalar(query)
        if job is None:
            self.session.rollback()
            return None
        token = secrets.token_urlsafe(32)
        job.status = "running"
        job.attempt_count += 1
        job.lease_owner = self.worker_id
        job.lease_token_hash = _hash(token)
        job.lease_generation += 1
        job.leased_until = now + timedelta(seconds=self.lease_seconds)
        job.heartbeat_at = now
        job.updated_at = now
        self.session.commit()
        return job, token

    def _guarded(self, job_id: str, token: str, values: dict) -> None:
        now = datetime.now(UTC)
        result = self.session.execute(
            update(DeploymentJob)
            .where(
                DeploymentJob.id == job_id,
                DeploymentJob.status == "running",
                DeploymentJob.lease_owner == self.worker_id,
                DeploymentJob.lease_token_hash == _hash(token),
                DeploymentJob.leased_until > now,
            )
            .values(updated_at=now, **values)
        )
        if result.rowcount != 1:
            self.session.rollback()
            raise LeaseLost("worker lease is no longer valid")
        self.session.commit()

    def heartbeat(self, job_id: str, token: str) -> None:
        now = datetime.now(UTC)
        self._guarded(
            job_id,
            token,
            {"heartbeat_at": now, "leased_until": now + timedelta(seconds=self.lease_seconds)},
        )

    def cancel(self, job_id: str) -> None:
        self.session.execute(
            update(DeploymentJob)
            .where(
                DeploymentJob.id == job_id,
                DeploymentJob.status.in_(["queued", "retry_wait", "running"]),
            )
            .values(cancellation_requested_at=datetime.now(UTC))
        )
        self.session.commit()

    def complete(self, job_id: str, token: str, success: bool) -> None:
        deployment_id = self.session.scalar(
            select(DeploymentJob.deployment_id).where(DeploymentJob.id == job_id)
        )
        if deployment_id is None:
            raise LeaseLost("job not found")
        self._guarded(
            job_id,
            token,
            {"status": "succeeded" if success else "failed", "completed_at": datetime.now(UTC)},
        )
        deployment = self.session.get(Deployment, deployment_id)
        if deployment is None:
            raise LeaseLost("deployment not found")
        service = DeploymentService(self.session)
        if success:
            for target in ("building", "built", "deploying", "verifying", "active"):
                service.transition(
                    deployment.id, target, expected_version=deployment.transition_version
                )
                self.session.refresh(deployment)
        else:
            service.transition(
                deployment.id, "failed", expected_version=deployment.transition_version
            )

    def process_once(self, executor: SimulatedExecutor | None = None) -> bool:
        claimed = self.claim()
        if claimed is None:
            return False
        job, token = claimed
        executor = executor or SimulatedExecutor()
        try:
            outcome = executor.run(
                lambda: (
                    self.session.scalar(
                        select(DeploymentJob.cancellation_requested_at).where(
                            DeploymentJob.id == job.id
                        )
                    )
                    is not None
                )
            )
            if outcome == "cancelled":
                self._guarded(
                    job.id, token, {"status": "cancelled", "completed_at": datetime.now(UTC)}
                )
            elif outcome == "retryable_failure" and job.attempt_count < min(
                job.max_attempts, self.max_attempts
            ):
                delay = min(300, 2 ** max(0, job.attempt_count - 1))
                self._guarded(
                    job.id,
                    token,
                    {
                        "status": "retry_wait",
                        "available_at": datetime.now(UTC) + timedelta(seconds=delay),
                        "last_error_code": "simulated_retryable",
                    },
                )
            else:
                self.complete(job.id, token, outcome == "success")
        except LeaseLost:
            log.warning("worker_lease_lost", job_id=job.id, worker_id=self.worker_id)
        return True


def run_worker(session_factory: Callable[[], Session], worker_id: str) -> None:
    stop = False

    def request_stop(*_args) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop:
        with session_factory() as session:
            if not DeploymentWorker(session, worker_id).process_once():
                time.sleep(1)


if __name__ == "__main__":
    from uuid import uuid4

    from lava.core.settings import get_settings
    from lava.persistence.database import engine_for_url

    settings = get_settings()
    engine = engine_for_url(settings.database_url.get_secret_value())
    run_worker(lambda: Session(engine), f"worker-{uuid4().hex[:12]}")
