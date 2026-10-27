"""PostgreSQL authorization and replay tests for external execution."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lava.application.executor_authorization import ExecutorDenied, authorize
from lava.application.executor_protocol import ExecutorRequest
from lava.db.base import (
    BuildExecution,
    Deployment,
    DeploymentJob,
    Environment,
    Project,
    Service,
    User,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def claimed():
    if os.environ.get("LAVA_INTEGRATION") != "1":
        pytest.skip("requires disposable PostgreSQL")
    engine = create_engine(os.environ["LAVA_DATABASE_URL"])
    suffix = uuid4().hex
    with Session(engine) as db:
        user = User(name="executor-" + suffix)
        db.add(user)
        db.flush()
        project = Project(name="executor-" + suffix, owner_id=user.id)
        db.add(project)
        db.flush()
        env = Environment(project_id=project.id, name="test", slug="test")
        db.add(env)
        db.flush()
        service = Service(
            project_id=project.id,
            environment_id=env.id,
            name="api",
            service_type="web",
            resources={"cpu": 1, "memory_mb": 512},
        )
        db.add(service)
        db.flush()
        deployment = Deployment(
            project_id=project.id,
            environment_id=env.id,
            service_id=service.id,
            source_type="git",
            repository_url="https://github.com/ralphdeeney/lava",
            source_commit_sha="a" * 40,
            source_branch="main",
            configuration_revision=1,
            idempotency_key=suffix,
            created_by=user.id,
        )
        db.add(deployment)
        db.flush()
        db.add(DeploymentJob(deployment_id=deployment.id))
        db.commit()
        import hashlib

        token = "1." + uuid4().hex
        job = db.scalar(select(DeploymentJob).where(DeploymentJob.deployment_id == deployment.id))
        job.status = "running"
        job.attempt_count = 1
        job.lease_owner = "executor-test"
        job.lease_generation = 1
        job.lease_token_hash = hashlib.sha256(token.encode()).hexdigest()
        job.leased_until = datetime.now(UTC) + timedelta(minutes=1)
        db.commit()
        req = ExecutorRequest(
            str(uuid4()),
            job.id,
            deployment.id,
            job.lease_generation,
            deployment.source_commit_sha,
            1,
            "python",
            "start",
            uuid4().hex * 2,
            int(datetime.now(UTC).timestamp()) + 30,
            lease_owner="executor-test",
            lease_token=token,
        )
    yield engine, req
    with Session(engine) as cleanup:
        job = cleanup.get(DeploymentJob, req.job_id)
        if job.status not in {"succeeded", "failed", "cancelled"}:
            job.status = "failed"
            cleanup.commit()
    engine.dispose()


def test_durable_replay_identity_and_stale_generation(claimed):
    engine, req = claimed
    with Session(engine) as db:
        assert authorize(db, req).status == "UNKNOWN"
        with pytest.raises(ExecutorDenied):
            authorize(db, req)
        with pytest.raises(ExecutorDenied):
            authorize(
                db, replace(req, claim_generation=req.claim_generation + 1, nonce=uuid4().hex * 2)
            )
        with pytest.raises(ExecutorDenied):
            authorize(db, replace(req, source_commit="b" * 40, nonce=uuid4().hex * 2))
        with pytest.raises(ExecutorDenied):
            authorize(db, replace(req, execution_id=str(uuid4()), nonce=uuid4().hex * 2))
        assert (
            db.scalar(select(BuildExecution).where(BuildExecution.id == req.execution_id))
            is not None
        )


def test_concurrent_duplicate_start_has_one_winner(claimed):
    engine, req = claimed

    def attempt():
        with Session(engine) as db:
            try:
                authorize(db, req)
                return "accepted"
            except ExecutorDenied:
                return "replayed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["accepted", "replayed"]


def test_expiry_bad_token_and_transaction_rollback(claimed):
    engine, req = claimed
    with Session(engine) as db:
        with pytest.raises(ValueError):
            authorize(db, replace(req, expires_at=1))
        with pytest.raises(ExecutorDenied):
            authorize(db, replace(req, lease_token="wrong"))
        assert db.get(BuildExecution, req.execution_id) is None
        assert authorize(db, req).id == req.execution_id
        with pytest.raises(ExecutorDenied):
            authorize(db, req)
        assert db.get(BuildExecution, req.execution_id) is not None


def test_cancelled_job_cannot_start_and_reclaimed_lease_fences_old_request(claimed):
    engine, req = claimed
    with Session(engine) as db:
        job = db.get(DeploymentJob, req.job_id)
        job.cancellation_requested_at = datetime.now(UTC)
        db.commit()
        with pytest.raises(ExecutorDenied):
            authorize(db, req)
        job = db.get(DeploymentJob, req.job_id)
        job.cancellation_requested_at = None
        job.lease_generation += 1
        db.commit()
        with pytest.raises(ExecutorDenied):
            authorize(db, req)
        assert db.get(BuildExecution, req.execution_id) is None


def test_unknown_blocks_reclaimed_attempt_and_stale_completion(claimed):
    from lava.application.executor_recovery import StaleExecution, reconcile

    engine, req = claimed
    with Session(engine) as db:
        authorize(db, req)
        assert reconcile(db, req.execution_id, "UNKNOWN") == "UNKNOWN"
        job = db.get(DeploymentJob, req.job_id)
        job.lease_generation += 1
        db.commit()
        with pytest.raises(StaleExecution):
            reconcile(db, req.execution_id, "COMPLETED")
        newer = replace(
            req,
            execution_id=str(uuid4()),
            claim_generation=req.claim_generation + 1,
            nonce=uuid4().hex * 2,
        )
        job = db.get(DeploymentJob, req.job_id)
        job.lease_token_hash = __import__("hashlib").sha256(req.lease_token.encode()).hexdigest()
        db.commit()
        with pytest.raises(ExecutorDenied, match="uncertain"):
            authorize(db, newer)


def test_build_publication_is_atomic_and_probe_cannot_forge_image(claimed, monkeypatch):
    from lava.application.deployments import DeploymentService
    from lava.db.base import BuildArtifact, DeploymentEvent
    from lava.worker import DeploymentWorker, LeaseLost

    engine, req = claimed
    with Session(engine) as db:
        execution = authorize(db, req, kind="fixture-build")
        execution.status = "COMPLETED"
        execution.image_digest = "sha256:" + "c" * 64
        db.add(DeploymentEvent(deployment_id=req.deployment_id, sequence=0, to_status="queued"))
        db.commit()
        result = {"execution_id": execution.id, "image_digest": execution.image_digest}
        worker = DeploymentWorker(db, req.lease_owner)
        original = DeploymentService.transition

        def interrupted(*args, **kwargs):
            raise RuntimeError("injected transaction interruption")

        monkeypatch.setattr(DeploymentService, "transition", interrupted)
        with pytest.raises(RuntimeError, match="interruption"):
            worker.complete(req.job_id, req.lease_token, True, build_result=result)
        assert (
            db.scalar(select(BuildArtifact).where(BuildArtifact.deployment_id == req.deployment_id))
            is None
        )
        assert db.get(DeploymentJob, req.job_id).status == "running"
        assert db.get(Deployment, req.deployment_id).status == "queued"
        monkeypatch.setattr(DeploymentService, "transition", original)
        execution = db.get(BuildExecution, req.execution_id)
        execution.kind = "controlled-probe"
        db.commit()
        with pytest.raises(LeaseLost):
            worker.complete(req.job_id, req.lease_token, True, build_result=result)
        execution = db.get(BuildExecution, req.execution_id)
        execution.kind = "fixture-build"
        db.commit()
        worker.complete(req.job_id, req.lease_token, True, build_result=result)
        assert db.get(DeploymentJob, req.job_id).status == "succeeded"
        assert db.get(Deployment, req.deployment_id).status == "built"
        assert (
            db.scalar(
                select(BuildArtifact).where(BuildArtifact.deployment_id == req.deployment_id)
            ).image_digest
            == result["image_digest"]
        )
