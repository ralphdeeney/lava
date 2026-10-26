"""Lease-fenced persistence of immutable OCI build results."""

import hashlib
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from lava.db.base import BuildArtifact, Deployment, DeploymentJob
from lava.worker import LeaseLost

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def record_build_artifact(
    session: Session,
    *,
    job_id: str,
    lease_owner: str,
    lease_token: str,
    image_digest: str,
    railpack_version: str,
    buildkit_version: str,
    commit: bool = True,
) -> BuildArtifact:
    if not DIGEST.fullmatch(image_digest):
        raise ValueError("Invalid OCI image digest")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", railpack_version):
        raise ValueError("Invalid Railpack version")
    if not re.fullmatch(r"v?[0-9]+\.[0-9]+\.[0-9]+", buildkit_version):
        raise ValueError("Invalid BuildKit version")
    try:
        job = session.scalar(
            select(DeploymentJob).where(DeploymentJob.id == job_id).with_for_update()
        )
        if (
            job is None
            or job.status != "running"
            or job.lease_owner != lease_owner
            or job.lease_token_hash != hashlib.sha256(lease_token.encode()).hexdigest()
            or job.lease_generation != int(lease_token.split(".", 1)[0])
            or job.leased_until <= datetime.now(UTC)
        ):
            raise LeaseLost("worker lease is no longer valid")
        deployment = session.get(Deployment, job.deployment_id)
        existing = session.scalar(
            select(BuildArtifact).where(
                BuildArtifact.deployment_id == deployment.id,
                BuildArtifact.attempt == job.attempt_count,
            )
        )
        if existing is not None:
            if existing.image_digest != image_digest:
                raise ValueError("Build attempt already recorded with a different digest")
            if commit:
                session.commit()
            return existing
        artifact = BuildArtifact(
            deployment_id=deployment.id,
            attempt=job.attempt_count,
            source_commit_sha=deployment.source_commit_sha,
            configuration_revision=deployment.configuration_revision,
            railpack_version=railpack_version,
            buildkit_version=buildkit_version,
            image_digest=image_digest,
        )
        session.add(artifact)
        session.flush()
        if commit:
            session.commit()
        return artifact
    except Exception:
        session.rollback()
        raise
