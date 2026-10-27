"""Standalone PostgreSQL deployment worker with a deterministic simulated executor."""

from __future__ import annotations

import hashlib
import secrets
import signal
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from lava.application.deployments import DeploymentService
from lava.application.executor_client import ExecutionUncertain
from lava.core.settings import Settings, get_settings
from lava.db.base import BuildExecution, Deployment, DeploymentJob

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
        self,
        session: Session,
        worker_id: str,
        lease_seconds: int = 60,
        max_attempts: int = 3,
        heartbeat_interval: float | None = None,
        retry_backoff: float = 1.0,
    ):
        self.session = session
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.heartbeat_interval = heartbeat_interval or lease_seconds / 3
        self.retry_backoff = retry_backoff

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
            .where(
                ~select(BuildExecution.id)
                .where(
                    BuildExecution.job_id == DeploymentJob.id,
                    BuildExecution.status.in_(["RUNNING", "UNKNOWN"]),
                )
                .exists()
            )
            .order_by(DeploymentJob.priority.desc(), DeploymentJob.available_at, DeploymentJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = self.session.scalar(query)
        if job is None:
            self.session.rollback()
            return None
        token = f"{job.lease_generation + 1}.{secrets.token_urlsafe(32)}"
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
                DeploymentJob.lease_generation == int(token.split(".", 1)[0]),
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
        try:
            job = self.session.scalar(
                select(DeploymentJob).where(DeploymentJob.id == job_id).with_for_update()
            )
            if job is None or job.status in {"succeeded", "failed", "cancelled"}:
                self.session.rollback()
                return
            job.cancellation_requested_at = datetime.now(UTC)
            if job.status != "running":
                deployment = self.session.get(Deployment, job.deployment_id)
                DeploymentService(self.session).transition(
                    deployment.id,
                    "cancelled",
                    expected_version=deployment.transition_version,
                    commit=False,
                )
                job.status = "cancelled"
                job.completed_at = datetime.now(UTC)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def complete(
        self, job_id: str, token: str, success: bool, *, build_result: dict | None = None
    ) -> None:
        try:
            job = self.session.scalar(
                select(DeploymentJob).where(DeploymentJob.id == job_id).with_for_update()
            )
            if job is not None:
                self.session.refresh(job)
            now = datetime.now(UTC)
            if (
                job is None
                or job.status != "running"
                or job.lease_owner != self.worker_id
                or job.lease_token_hash != _hash(token)
                or job.lease_generation != int(token.split(".", 1)[0])
                or job.leased_until <= now
            ):
                raise LeaseLost("worker lease is no longer valid")
            deployment = self.session.get(Deployment, job.deployment_id)
            if deployment is None:
                raise LeaseLost("deployment not found")
            if build_result is not None and not job.cancellation_requested_at:
                from lava.application.build_artifacts import record_build_artifact

                execution = self.session.get(BuildExecution, build_result["execution_id"])
                if (
                    execution is None
                    or execution.job_id != job.id
                    or execution.claim_generation != job.lease_generation
                    or execution.kind != "fixture-build"
                    or execution.status != "COMPLETED"
                    or execution.image_digest != build_result["image_digest"]
                ):
                    raise LeaseLost("Build result does not belong to the current claim")
                record_build_artifact(
                    self.session,
                    job_id=job.id,
                    lease_owner=self.worker_id,
                    lease_token=token,
                    image_digest=execution.image_digest,
                    railpack_version="0.43.0",
                    buildkit_version="v0.34.0",
                    commit=False,
                )
            targets = (
                ["cancelled"]
                if job.cancellation_requested_at
                else (
                    (
                        ["building", "built"]
                        if build_result is not None
                        else ["building", "built", "deploying", "verifying", "active"]
                    )
                    if success
                    else ["failed"]
                )
            )
            service = DeploymentService(self.session)
            for target in targets:
                service.transition(
                    deployment.id,
                    target,
                    expected_version=deployment.transition_version,
                    commit=False,
                )
                self.session.refresh(deployment)
            job.status = (
                "cancelled"
                if job.cancellation_requested_at
                else ("succeeded" if success else "failed")
            )
            job.completed_at = now
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def process_once(
        self, executor: SimulatedExecutor | None = None, *, executor_factory=None
    ) -> bool:
        claimed = self.claim()
        if claimed is None:
            return False
        job, token = claimed
        if executor_factory is not None:
            executor = executor_factory(job, self.session.get(Deployment, job.deployment_id), token)
        executor = executor or SimulatedExecutor()
        stop_heartbeat = threading.Event()
        lease_lost = threading.Event()
        engine = self.session.get_bind()

        def renew_lease() -> None:
            interval = self.heartbeat_interval
            while not stop_heartbeat.wait(interval):
                try:
                    with Session(engine) as heartbeat_session:
                        DeploymentWorker(
                            heartbeat_session, self.worker_id, self.lease_seconds
                        ).heartbeat(job.id, token)
                except Exception as error:
                    log.warning(
                        "worker_heartbeat_failed", job_id=job.id, error_type=type(error).__name__
                    )
                    lease_lost.set()
                    return

        heartbeat_thread = threading.Thread(target=renew_lease, daemon=True)
        heartbeat_thread.start()
        try:
            outcome = executor.run(
                lambda: (
                    lease_lost.is_set()
                    or self.session.scalar(
                        select(DeploymentJob.cancellation_requested_at).where(
                            DeploymentJob.id == job.id
                        )
                    )
                    is not None
                )
            )
            # Resolve an in-flight renewal before publishing an outcome. Otherwise
            # its database failure can be observed only after completion commits.
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=max(1, self.lease_seconds / 3 + 1))
            if heartbeat_thread.is_alive() or lease_lost.is_set():
                raise LeaseLost("heartbeat failed or lease was reclaimed")
            if outcome == "cancelled":
                self.cancel(job.id)
                self.complete(job.id, token, False)
            elif outcome == "retryable_failure" and job.attempt_count < min(
                job.max_attempts, self.max_attempts
            ):
                delay = min(300, self.retry_backoff * 2 ** max(0, job.attempt_count - 1))
                self._guarded(
                    job.id,
                    token,
                    {
                        "status": "retry_wait",
                        "available_at": datetime.now(UTC) + timedelta(seconds=delay),
                        "last_error_code": "simulated_retryable",
                    },
                )
            elif outcome == "built":
                self.complete(job.id, token, True, build_result=executor.result)
            else:
                self.complete(job.id, token, outcome == "success")
        except LeaseLost:
            log.warning("worker_lease_lost", job_id=job.id, worker_id=self.worker_id)
        except ExecutionUncertain:
            self.session.rollback()
            log.warning("worker_execution_uncertain", job_id=job.id, worker_id=self.worker_id)
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=max(1, self.lease_seconds / 3 + 1))
        return True


def run_worker(
    session_factory: Callable[[], Session], worker_id: str, settings: Settings | None = None
) -> None:
    settings = settings or get_settings()
    stop = threading.Event()

    def request_stop(*_args) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    executor_factory = None
    if settings.worker_executor_mode in {"controlled-probe", "fixture-build"}:
        from pathlib import Path

        from lava.application.executor_client import SocketExecutor
        from lava.executor import load_key

        key = load_key(Path(settings.executor_key_file))

        def executor_factory(job, deployment, token):
            return SocketExecutor(
                Path(settings.executor_socket),
                key,
                job,
                deployment,
                token,
                settings.executor_fixture,
                mode=settings.worker_executor_mode,
            )

    while not stop.is_set():
        try:
            with session_factory() as session:
                processed = DeploymentWorker(
                    session,
                    worker_id,
                    settings.worker_lease_seconds,
                    settings.worker_max_attempts,
                    settings.worker_heartbeat_interval_seconds,
                    settings.worker_retry_backoff_seconds,
                ).process_once(executor_factory=executor_factory)
            if not processed:
                stop.wait(settings.worker_poll_interval_seconds)
        except Exception as error:
            log.warning(
                "worker_database_unavailable", worker_id=worker_id, error_type=type(error).__name__
            )
            stop.wait(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    from uuid import uuid4

    from lava.core.settings import get_settings
    from lava.persistence.database import engine_for_url

    settings = get_settings()
    engine = engine_for_url(settings.database_url.get_secret_value())
    run_worker(lambda: Session(engine), f"worker-{uuid4().hex[:12]}", settings)
