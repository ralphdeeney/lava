"""Real PostgreSQL regression cases for job/deployment consistency."""

import os
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from lava.application.deployments import DeploymentService
from lava.db.base import (
    Deployment,
    DeploymentEvent,
    DeploymentJob,
    Environment,
    Project,
    Service,
    User,
)
from lava.worker import DeploymentWorker, LeaseLost

pytestmark = pytest.mark.integration


@pytest.fixture
def worker_database():
    if os.environ.get("LAVA_INTEGRATION") != "1":
        pytest.skip("requires disposable PostgreSQL")
    url = os.environ["LAVA_DATABASE_URL"]
    if os.environ.get("LAVA_TEST_DATABASE_RESET") != "1" or not make_url(url).database.endswith(
        "_test"
    ):
        pytest.fail("requires acknowledged disposable *_test database")
    engine = create_engine(url)
    suffix = uuid4().hex
    with Session(engine) as session:
        user = User(name="worker-" + suffix)
        session.add(user)
        session.flush()
        project = Project(name="worker-" + suffix, owner_id=user.id)
        session.add(project)
        session.flush()
        environment = Environment(project_id=project.id, name="test", slug="test")
        session.add(environment)
        session.flush()
        service = Service(
            project_id=project.id,
            environment_id=environment.id,
            name="api",
            service_type="web",
            resources={"cpu": 1, "memory_mb": 512},
        )
        session.add(service)
        session.flush()
        deployment = Deployment(
            project_id=project.id,
            environment_id=environment.id,
            service_id=service.id,
            source_type="git",
            source_commit_sha="abcdef1234567",
            source_branch="main",
            configuration_revision=1,
            idempotency_key=suffix,
            created_by=user.id,
        )
        session.add(deployment)
        session.flush()
        job = DeploymentJob(deployment_id=deployment.id)
        session.add_all(
            [job, DeploymentEvent(deployment_id=deployment.id, sequence=0, to_status="queued")]
        )
        session.commit()
        yield engine, job.id, deployment.id
        session.delete(job)
        session.query(DeploymentEvent).filter_by(deployment_id=deployment.id).delete()
        session.delete(deployment)
        session.flush()
        session.delete(service)
        session.flush()
        session.delete(environment)
        session.flush()
        session.delete(project)
        session.flush()
        session.delete(user)
        session.commit()
    engine.dispose()


def test_failure_completion_is_atomic_and_legal_from_queued(worker_database):
    engine, job_id, deployment_id = worker_database
    with Session(engine) as session:
        worker = DeploymentWorker(session, "worker-a")
        job, token = worker.claim()
        assert job.id == job_id
        worker.complete(job_id, token, False)
    with Session(engine) as session:
        assert session.get(DeploymentJob, job_id).status == "failed"
        assert session.get(Deployment, deployment_id).status == "failed"
        assert [
            e.sequence
            for e in session.scalars(
                select(DeploymentEvent)
                .where(DeploymentEvent.deployment_id == deployment_id)
                .order_by(DeploymentEvent.sequence)
            )
        ] == [0, 1]


def test_cancel_before_claim_updates_deployment(worker_database):
    engine, job_id, deployment_id = worker_database
    with Session(engine) as session:
        DeploymentWorker(session, "worker-a").cancel(job_id)
    with Session(engine) as session:
        assert session.get(DeploymentJob, job_id).status == "cancelled"
        assert session.get(Deployment, deployment_id).status == "cancelled"


def test_transition_failure_rolls_back_job_and_events(worker_database, monkeypatch):
    engine, job_id, deployment_id = worker_database
    with Session(engine) as session:
        worker = DeploymentWorker(session, "worker-a")
        _, token = worker.claim()
        original = DeploymentService.transition

        def fail_after_first(self, deployment_id, target, **kwargs):
            result = original(self, deployment_id, target, **kwargs)
            if target == "building":
                raise RuntimeError("injected transition interruption")
            return result

        monkeypatch.setattr(DeploymentService, "transition", fail_after_first)
        with pytest.raises(RuntimeError, match="injected"):
            worker.complete(job_id, token, True)
    with Session(engine) as session:
        assert session.get(DeploymentJob, job_id).status == "running"
        assert session.get(Deployment, deployment_id).status == "queued"
        assert (
            session.scalar(
                select(DeploymentEvent).where(
                    DeploymentEvent.deployment_id == deployment_id, DeploymentEvent.sequence == 1
                )
            )
            is None
        )


def test_reclaimed_lease_fences_stale_worker(worker_database):
    engine, job_id, deployment_id = worker_database
    with Session(engine) as first:
        _, old_token = DeploymentWorker(first, "worker-a").claim()
        job = first.get(DeploymentJob, job_id)
        job.leased_until = datetime.now(UTC) - timedelta(seconds=1)
        first.commit()
    with Session(engine) as second:
        _, new_token = DeploymentWorker(second, "worker-b").claim()
        assert new_token != old_token
    with Session(engine) as first:
        with pytest.raises(LeaseLost):
            DeploymentWorker(first, "worker-a").complete(job_id, old_token, True)
    with Session(engine) as second:
        DeploymentWorker(second, "worker-b").complete(job_id, new_token, True)
    with Session(engine) as session:
        assert session.get(DeploymentJob, job_id).status == "succeeded"
        assert session.get(Deployment, deployment_id).status == "active"


def test_cancel_running_job_wins_before_completion(worker_database):
    engine, job_id, deployment_id = worker_database
    with Session(engine) as first:
        _, token = DeploymentWorker(first, "worker-a").claim()
    with Session(engine) as second:
        DeploymentWorker(second, "worker-b").cancel(job_id)
    with Session(engine) as first:
        DeploymentWorker(first, "worker-a").complete(job_id, token, True)
    with Session(engine) as session:
        assert session.get(DeploymentJob, job_id).status == "cancelled"
        assert session.get(Deployment, deployment_id).status == "cancelled"


def test_heartbeat_keeps_lease_during_long_execution(worker_database):
    engine, job_id, deployment_id = worker_database

    class SlowExecutor:
        def run(self, cancelled):
            time.sleep(2.4)
            return "cancelled" if cancelled() else "success"

    with Session(engine) as session:
        assert DeploymentWorker(session, "worker-a", lease_seconds=1.5).process_once(SlowExecutor())
    with Session(engine) as session:
        assert session.get(DeploymentJob, job_id).status == "succeeded"
        assert session.get(Deployment, deployment_id).status == "active"


def test_two_workers_cannot_claim_same_live_lease(worker_database):
    engine, job_id, _ = worker_database
    with Session(engine) as first, Session(engine) as second:
        claimed, _ = DeploymentWorker(first, "worker-a").claim()
        assert claimed.id == job_id
        assert DeploymentWorker(second, "worker-b").claim() is None


def test_cancel_during_retry_backoff_is_terminal(worker_database):
    engine, job_id, deployment_id = worker_database
    with Session(engine) as session:
        worker = DeploymentWorker(session, "worker-a")
        _, token = worker.claim()
        worker._guarded(
            job_id,
            token,
            {"status": "retry_wait", "available_at": datetime.now(UTC) + timedelta(seconds=10)},
        )
    with Session(engine) as session:
        DeploymentWorker(session, "worker-b").cancel(job_id)
    with Session(engine) as session:
        assert session.get(DeploymentJob, job_id).status == "cancelled"
        assert session.get(Deployment, deployment_id).status == "cancelled"
