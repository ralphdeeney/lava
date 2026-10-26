"""Transactional authorization of fixture execution against a live job lease."""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from lava.application.executor_protocol import ExecutorRequest
from lava.db.base import BuildExecution, BuildRequestNonce, Deployment, DeploymentJob


class ExecutorDenied(PermissionError):
    pass


def authorize(session: Session, request: ExecutorRequest) -> BuildExecution:
    """Consume a nonce and authorize one operation in the same transaction.

    The caller performs the external action only after this transaction commits.
    """
    try:
        request.validate(datetime.now(UTC).timestamp())
        job = session.scalar(
            select(DeploymentJob).where(DeploymentJob.id == request.job_id).with_for_update()
        )
        now = datetime.now(UTC)
        if (
            job is None
            or job.deployment_id != request.deployment_id
            or job.status != "running"
            or job.lease_generation != request.claim_generation
            or job.lease_owner != request.lease_owner
            or job.lease_token_hash != hashlib.sha256(request.lease_token.encode()).hexdigest()
            or job.leased_until is None
            or job.leased_until <= now
        ):
            raise ExecutorDenied("No current job lease")
        deployment = session.get(Deployment, job.deployment_id)
        if (
            deployment is None
            or deployment.source_commit_sha != request.source_commit
            or deployment.configuration_revision != request.configuration_revision
        ):
            raise ExecutorDenied("Source identity mismatch")
        if request.operation == "start" and job.cancellation_requested_at is not None:
            raise ExecutorDenied("Cancellation already requested")
        execution = session.get(BuildExecution, request.execution_id)
        if request.operation == "start":
            if execution is None:
                conflict = session.scalar(
                    select(BuildExecution).where(
                        BuildExecution.job_id == job.id,
                        BuildExecution.claim_generation == job.lease_generation,
                    )
                )
                if conflict is not None:
                    raise ExecutorDenied("Claim already has a different execution identity")
                previous = session.scalar(
                    select(BuildExecution)
                    .where(
                        BuildExecution.job_id == job.id,
                        BuildExecution.status.in_(["UNKNOWN", "RUNNING"]),
                    )
                    .limit(1)
                )
                if previous is not None:
                    raise ExecutorDenied("Previous external execution has uncertain outcome")
                execution = BuildExecution(
                    id=request.execution_id,
                    job_id=job.id,
                    deployment_id=deployment.id,
                    claim_generation=job.lease_generation,
                    source_commit_sha=request.source_commit,
                    configuration_revision=request.configuration_revision,
                    fixture=request.fixture,
                    status="UNKNOWN",
                )
                session.add(execution)
                session.flush()
            elif execution.status not in {"UNKNOWN", "RUNNING"}:
                raise ExecutorDenied("Execution is terminal")
        if (
            execution is None
            or execution.job_id != job.id
            or execution.deployment_id != deployment.id
            or execution.claim_generation != job.lease_generation
            or execution.source_commit_sha != request.source_commit
            or execution.configuration_revision != request.configuration_revision
            or execution.fixture != request.fixture
        ):
            raise ExecutorDenied("Execution identity conflict")
        if request.operation in {"result", "cleanup"} and execution.status == "RUNNING":
            raise ExecutorDenied("Execution is still active")
        session.add(
            BuildRequestNonce(
                nonce_hash=hashlib.sha256(request.nonce.encode()).hexdigest(),
                execution_id=execution.id,
                expires_at=datetime.fromtimestamp(request.expires_at, UTC),
            )
        )
        session.commit()
        return execution
    except Exception:
        session.rollback()
        raise
