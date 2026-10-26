"""Disposable Compose-only probe of the running worker and socket executor."""

import os
import time
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from lava.core.settings import get_settings
from lava.db.base import (
    BuildArtifact,
    BuildExecution,
    Deployment,
    DeploymentEvent,
    DeploymentJob,
    Environment,
    Project,
    Service,
    User,
)


def main():
    settings = get_settings()
    url = settings.database_url.get_secret_value()
    if (
        settings.environment != "test"
        or not make_url(url).database.endswith("_test")
        or os.environ.get("LAVA_DISPOSABLE_EXECUTOR_PROBE") != "1"
    ):
        raise RuntimeError("Executor probe requires an explicitly disposable test stack")
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            user = User(name="executor-probe-" + uuid4().hex)
            db.add(user)
            db.flush()
            project = Project(name="executor-probe-" + uuid4().hex, owner_id=user.id)
            db.add(project)
            db.flush()
            environment = Environment(project_id=project.id, name="probe", slug="probe")
            db.add(environment)
            db.flush()
            service = Service(
                project_id=project.id,
                environment_id=environment.id,
                name="probe",
                service_type="web",
                resources={"cpu": 1, "memory_mb": 512},
            )
            db.add(service)
            db.flush()
            deployment = Deployment(
                project_id=project.id,
                environment_id=environment.id,
                service_id=service.id,
                source_type="git",
                source_commit_sha="a" * 40,
                source_branch="probe",
                configuration_revision=1,
                idempotency_key=uuid4().hex,
                created_by=user.id,
            )
            db.add(deployment)
            db.flush()
            job = DeploymentJob(deployment_id=deployment.id)
            db.add_all(
                [job, DeploymentEvent(deployment_id=deployment.id, sequence=0, to_status="queued")]
            )
            db.commit()
            job_id, deployment_id = job.id, deployment.id
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            with Session(engine) as db:
                job = db.get(DeploymentJob, job_id)
                if job.status == "succeeded":
                    execution = db.scalar(
                        select(BuildExecution).where(BuildExecution.job_id == job_id)
                    )
                    assert (
                        execution is not None
                        and execution.status == "COMPLETED"
                        and execution.kind == "controlled-probe"
                    )
                    assert (
                        db.scalar(
                            select(BuildArtifact).where(
                                BuildArtifact.deployment_id == deployment_id
                            )
                        )
                        is None
                    )
                    print("PASS: controlled executor lifecycle; no image built")
                    return
            time.sleep(0.2)
        raise RuntimeError("Controlled executor probe did not finish")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
