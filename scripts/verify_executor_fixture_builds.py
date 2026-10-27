"""Protected-main-only build verification through the authenticated boundary.

The Docker-capable executor runs on the disposable runner. Its worker runs in a
non-root, read-only container with no Docker socket and only a read-only mount
of the private executor transport. No API or infrastructure credentials enter it.
"""

import contextlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from lava.builds.fixture_toolchain import (
    BUILDER_NAME,
    BUILDKIT_IMAGE,
    FIXTURES,
    run,
    validate_trusted_source,
)
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
from lava.executor import provision_key
from lava.persistence.executor_role import provision
from lava.worker import DeploymentWorker

ROOT = Path(__file__).resolve().parents[1]
WORKER = """
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from lava.core.settings import get_settings
from lava.application.executor_client import SocketExecutor
from lava.executor import load_key
from lava.worker import DeploymentWorker
s=get_settings()
e=create_engine(s.database_url.get_secret_value())
key=load_key(Path('/runtime/key'))
try:
    with Session(e) as db:
        assert DeploymentWorker(db, 'trusted-fixture-worker').process_once(
            executor_factory=lambda job, deployment, token: SocketExecutor(
                Path('/runtime/sock'), key, job, deployment, token,
                s.executor_fixture, mode='fixture-build'))
finally:
    e.dispose()
"""


def worker_command(name: str, image: str, runtime: Path) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "host",
        "--user",
        str(os.getuid()),
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=64m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "512m",
        "--cpus",
        "1",
        "--pids-limit",
        "64",
        "--mount",
        f"type=bind,src={runtime},dst=/runtime,readonly",
        "-e",
        "LAVA_DATABASE_URL",
        "-e",
        "LAVA_EXECUTOR_FIXTURE",
        "-e",
        "LAVA_WORKER_EXECUTOR_MODE",
        "-e",
        "LAVA_EXECUTOR_SOCKET",
        "-e",
        "LAVA_EXECUTOR_KEY_FILE",
        image,
        "python",
        "-c",
        WORKER,
    ]


def seed(engine, fixture, commit):
    with Session(engine) as db:
        user = User(name="fixture-" + uuid4().hex)
        db.add(user)
        db.flush()
        project = Project(name="fixture-" + uuid4().hex, owner_id=user.id)
        db.add(project)
        db.flush()
        environment = Environment(project_id=project.id, name="build", slug="build")
        db.add(environment)
        db.flush()
        service = Service(
            project_id=project.id,
            environment_id=environment.id,
            name=fixture,
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
            repository_url="https://github.com/ralphdeeney/lava",
            source_commit_sha=commit,
            source_branch="main",
            configuration_revision=1,
            idempotency_key=uuid4().hex,
            created_by=user.id,
        )
        db.add(deployment)
        db.flush()
        db.add_all(
            [
                DeploymentJob(deployment_id=deployment.id),
                DeploymentEvent(
                    deployment_id=deployment.id, sequence=0, to_status="queued"
                ),
            ]
        )
        db.commit()
        return deployment.id


def main():
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    for fixture in FIXTURES:
        validate_trusted_source(ROOT, commit, fixture)
    url = make_url(os.environ["LAVA_DATABASE_URL"])
    if url.database != "lava_test" or url.host != "127.0.0.1":
        raise RuntimeError(
            "Build verification requires its disposable local provenance database"
        )
    engine = create_engine(url)
    executor_role = "lava_exec_" + uuid4().hex[:12]
    worker_role = "lava_build_worker_" + uuid4().hex[:12]
    executor_password, worker_password = (
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(32),
    )
    admin = url.set(drivername="postgresql").render_as_string(hide_password=False)
    image = "lava-fixture-worker:" + commit[:12]
    evidence = []
    process = None
    runtime = None
    builder_created = False
    containers = []
    with psycopg.connect(admin) as connection:
        provision(connection, executor_password, executor_role)
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(worker_role), sql.Literal(worker_password)
            )
        )
        for grant in (
            "GRANT USAGE ON SCHEMA public TO {}",
            "GRANT SELECT, UPDATE ON deployment_jobs, deployments TO {}",
            "GRANT SELECT, INSERT ON deployment_events, build_artifacts TO {}",
            "GRANT SELECT ON build_executions TO {}",
        ):
            connection.execute(sql.SQL(grant).format(sql.Identifier(worker_role)))
    try:
        run(
            [
                "docker",
                "build",
                "-f",
                str(ROOT / "apps/api/Dockerfile"),
                "-t",
                image,
                str(ROOT),
            ]
        )
        run(
            [
                "docker",
                "buildx",
                "create",
                "--name",
                BUILDER_NAME,
                "--driver",
                "docker-container",
                "--driver-opt",
                f"image={BUILDKIT_IMAGE}",
                "--driver-opt",
                "memory=3g",
                "--driver-opt",
                "cpu-quota=200000",
                "--driver-opt",
                "cpu-period=100000",
            ],
            timeout=120,
        )
        builder_created = True

        def ensure_builder() -> None:
            """Recreate the single owned builder between terminal test cases."""
            nonlocal builder_created
            subprocess.run(
                ["docker", "buildx", "rm", "--force", BUILDER_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
            run(
                [
                    "docker",
                    "buildx",
                    "create",
                    "--name",
                    BUILDER_NAME,
                    "--driver",
                    "docker-container",
                    "--driver-opt",
                    f"image={BUILDKIT_IMAGE}",
                    "--driver-opt",
                    "memory=3g",
                    "--driver-opt",
                    "cpu-quota=200000",
                    "--driver-opt",
                    "cpu-period=100000",
                ],
                timeout=120,
            )
            run(
                [
                    "docker",
                    "buildx",
                    "inspect",
                    "--builder",
                    BUILDER_NAME,
                    "--bootstrap",
                ],
                timeout=120,
            )
            builder_created = True

        runtime = Path(tempfile.mkdtemp(prefix="lava-build-executor-"))
        provision_key(runtime / "key")
        executor_url = url.set(
            username=executor_role, password=executor_password
        ).render_as_string(hide_password=False)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"LAVA_DATABASE_URL", "GITHUB_TOKEN", "GH_TOKEN"}
        }
        environment.update(
            LAVA_EXECUTOR_DATABASE_URL=executor_url,
            LAVA_EXECUTOR_DATABASE_ROLE=executor_role,
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "lava.executor",
                "--socket",
                str(runtime / "sock"),
                "--key-file",
                str(runtime / "key"),
                "--mode",
                "fixture-build",
                "--source-root",
                str(ROOT),
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 15
        while not (runtime / "sock").exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Trusted build executor failed startup")
            time.sleep(0.1)
        for fixture in FIXTURES:
            container_name = "lava-fixture-worker-" + uuid4().hex[:12]
            containers.append(container_name)
            deployment_id = seed(engine, fixture, commit)
            worker_url = url.set(
                username=worker_role, password=worker_password
            ).render_as_string(hide_password=False)
            worker_env = {
                **os.environ,
                "LAVA_DATABASE_URL": worker_url,
                "LAVA_EXECUTOR_FIXTURE": fixture,
                "LAVA_WORKER_EXECUTOR_MODE": "fixture-build",
                "LAVA_EXECUTOR_SOCKET": "/runtime/sock",
                "LAVA_EXECUTOR_KEY_FILE": "/runtime/key",
            }
            # Command text is fixed trusted harness code, never PR input.
            subprocess.run(
                worker_command(container_name, image, runtime),
                env=worker_env,
                check=True,
                timeout=1560,
            )
            with Session(engine) as db:
                deployment = db.get(Deployment, deployment_id)
                artifact = db.scalar(
                    select(BuildArtifact).where(
                        BuildArtifact.deployment_id == deployment_id
                    )
                )
                if (
                    deployment.status != "built"
                    or artifact is None
                    or artifact.source_commit_sha != commit
                ):
                    raise RuntimeError("Worker did not publish a verified BUILT image")
                evidence.append(
                    {
                        "fixture": fixture,
                        "source_commit": commit,
                        "image_digest": artifact.image_digest,
                        "railpack_version": artifact.railpack_version,
                        "buildkit_version": artifact.buildkit_version,
                        "boundary": "authenticated-unix-socket-isolated-worker",
                        "status": "built",
                    }
                )
                print(
                    f"::notice::fixture={fixture} commit={commit} digest={artifact.image_digest}",
                    flush=True,
                )
        cases = (
            ("buildkit-fail", False),
            ("buildkit-cancel", True),
            ("buildkit-cancel", False),
        )
        for fixture, cancel in cases:
            container_name = "lava-fixture-worker-" + uuid4().hex[:12]
            containers.append(container_name)
            deployment_id = seed(engine, fixture, commit)
            worker_url = url.set(
                username=worker_role, password=worker_password
            ).render_as_string(hide_password=False)
            worker_env = {
                **os.environ,
                "LAVA_DATABASE_URL": worker_url,
                "LAVA_EXECUTOR_FIXTURE": fixture,
                "LAVA_WORKER_EXECUTOR_MODE": "fixture-build",
                "LAVA_EXECUTOR_SOCKET": "/runtime/sock",
                "LAVA_EXECUTOR_KEY_FILE": "/runtime/key",
            }
            command = worker_command(container_name, image, runtime)
            if fixture == "buildkit-cancel":
                worker_log = runtime / f"{fixture}-{uuid4().hex[:8]}.log"
                worker_output = worker_log.open("w+", encoding="utf-8")
                worker = subprocess.Popen(
                    command,
                    env=worker_env,
                    stdout=worker_output,
                    stderr=subprocess.STDOUT,
                )
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if worker.poll() is not None:
                        worker_output.flush()
                        worker_output.seek(0)
                        diagnostic = worker_output.read()[-4000:]
                        worker_output.close()
                        with Session(engine) as db:
                            early_job = db.scalar(
                                select(DeploymentJob).where(
                                    DeploymentJob.deployment_id == deployment_id
                                )
                            )
                            early_execution = db.scalar(
                                select(BuildExecution).where(
                                    BuildExecution.job_id == early_job.id
                                )
                            )
                            early_deployment = db.get(Deployment, deployment_id)
                        raise RuntimeError(
                            "Long-running fixture exited before BuildKit execution: "
                            f"returncode={worker.returncode} job={early_job.status} "
                            f"deployment={early_deployment.status} "
                            f"execution={early_execution.status if early_execution else 'missing'}; "
                            + re.sub(
                                r"(?i)(password|secret|token|key)=\S+",
                                r"\1=<redacted>",
                                diagnostic,
                            )
                        )
                    active = subprocess.check_output(["ps", "-eo", "args"], text=True)
                    buildkit = subprocess.run(
                        ["docker", "top", "buildx_buildkit_lava-fixtures0"],
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                    if (
                        "docker buildx build" in active
                        and "build-fixtures/buildkit-cancel" in active
                        and buildkit.returncode == 0
                        and b"sleep 180" in buildkit.stdout
                    ):
                        break
                    time.sleep(0.2)
                else:
                    raise RuntimeError(
                        "Timed out waiting for the actual BuildKit solve process"
                    )
                if cancel:
                    with Session(engine) as db:
                        job = db.scalar(
                            select(DeploymentJob).where(
                                DeploymentJob.deployment_id == deployment_id
                            )
                        )
                        DeploymentWorker(db, "trusted-fixture-worker").cancel(job.id)
                if worker.wait(timeout=60):
                    worker_output.flush()
                    worker_output.seek(0)
                    diagnostic = worker_output.read()[-4000:]
                    worker_output.close()
                    raise RuntimeError(
                        "Long-running fixture worker failed: "
                        + re.sub(
                            r"(?i)(password|secret|token|key)=\S+",
                            r"\1=<redacted>",
                            diagnostic,
                        )
                    )
                worker_output.close()
            else:
                subprocess.run(
                    command,
                    env=worker_env,
                    check=True,
                    timeout=90,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            with Session(engine) as db:
                job = db.scalar(
                    select(DeploymentJob).where(
                        DeploymentJob.deployment_id == deployment_id
                    )
                )
                execution = db.scalar(
                    select(BuildExecution).where(BuildExecution.job_id == job.id)
                )
                deployment = db.get(Deployment, deployment_id)
                expected = "cancelled" if cancel else "failed"
                if (
                    job.status != expected
                    or deployment.status != expected
                    or execution.status != expected.upper()
                    or execution.image_digest is not None
                    or db.scalar(
                        select(BuildArtifact).where(
                            BuildArtifact.deployment_id == deployment_id
                        )
                    )
                    is not None
                ):
                    raise RuntimeError(
                        "BuildKit terminal state or cleanup was inconsistent"
                    )
                expected_reason = (
                    "cancelled"
                    if cancel
                    else "process_failed"
                    if fixture == "buildkit-fail"
                    else "timeout"
                )
                receipt = json.loads(
                    (runtime / "processes" / execution.id / "result.json").read_text()
                )
                if (
                    receipt.get("execution_id") != execution.id
                    or receipt.get("status") != expected.upper()
                    or receipt.get("failure_code") != expected_reason
                ):
                    raise RuntimeError("BuildKit failure classification was not proven")
            ensure_builder()
            outcome = (
                "cancelled"
                if cancel
                else ("failed" if fixture == "buildkit-fail" else "timed_out")
            )
            evidence.append(
                {
                    "fixture": fixture,
                    "source_commit": commit,
                    "status": outcome,
                    "boundary": "authenticated-unix-socket-isolated-worker",
                    "builder_stopped": True,
                }
            )
            print(
                f"::notice::fixture={fixture} status={evidence[-1]['status']}",
                flush=True,
            )
        process.terminate()
        process.wait(timeout=10)
    finally:
        for container in containers:
            subprocess.run(
                ["docker", "rm", "-f", container],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        if process is not None and process.poll() is None:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
        if runtime is not None:
            shutil.rmtree(runtime)
        engine.dispose()
        if builder_created:
            subprocess.run(
                ["docker", "buildx", "rm", BUILDER_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
        subprocess.run(
            ["docker", "image", "rm", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
        with psycopg.connect(admin) as connection:
            for role in (worker_role, executor_role):
                connection.execute(
                    sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role))
                )
                connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
    output = ROOT / "test-results/fixture-builds.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        detail = re.sub(
            r"(?i)(password|token|secret|key)\s*[=:]\s*\S+",
            r"\1=[REDACTED]",
            str(error),
        )[:400]
        print(
            f"::error::Trusted executor fixture verification failed "
            f"({type(error).__name__}): {detail}",
            flush=True,
        )
        raise SystemExit(1) from None
