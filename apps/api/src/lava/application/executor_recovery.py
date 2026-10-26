"""Fenced reconciliation of external build state after executor interruptions."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from lava.db.base import BuildExecution, DeploymentJob


class StaleExecution(PermissionError):
    pass


def reconcile(session: Session, execution_id: str, observed: str) -> str:
    """Only a current claim can publish an observed terminal outcome.

    UNKNOWN is retained when the executor cannot prove the process outcome.
    """
    if observed not in {"RUNNING", "COMPLETED", "CANCELLED", "FAILED", "UNKNOWN"}:
        raise ValueError("Invalid executor observation")
    try:
        execution = session.scalar(
            select(BuildExecution).where(BuildExecution.id == execution_id).with_for_update()
        )
        if execution is None:
            raise StaleExecution("Execution not found")
        job = session.scalar(
            select(DeploymentJob).where(DeploymentJob.id == execution.job_id).with_for_update()
        )
        if (
            job is None
            or job.status != "running"
            or job.lease_generation != execution.claim_generation
            or job.leased_until is None
            or job.leased_until <= datetime.now(UTC)
        ):
            raise StaleExecution("Claim no longer owns this execution")
        if execution.status in {"COMPLETED", "CANCELLED", "FAILED"}:
            if execution.status != observed:
                raise StaleExecution("Terminal execution cannot change")
        elif observed == "COMPLETED" and job.cancellation_requested_at is not None:
            raise StaleExecution("Cancellation precludes success publication")
        else:
            execution.status = observed
        session.commit()
        return execution.status
    except Exception:
        session.rollback()
        raise
