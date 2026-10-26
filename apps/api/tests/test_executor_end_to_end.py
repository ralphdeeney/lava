"""Actual daemon, PostgreSQL, socket client and controlled child-process tests."""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_executor_authorization import claimed  # noqa: F401, F811

from lava.application.executor_authorization import authorize
from lava.application.executor_client import SocketExecutor
from lava.db.base import BuildExecution, Deployment, DeploymentEvent, DeploymentJob
from lava.executor import ExecutorService, exchange, load_key, provision_key
from lava.worker import DeploymentWorker

pytestmark = pytest.mark.integration


def until(check, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    pytest.fail("Timed out waiting for controlled executor condition")


@pytest.fixture
def daemon(claimed, tmp_path, executor_database):  # noqa: F811
    engine, req = claimed
    executor_url, executor_role = executor_database
    daemon_environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {"LAVA_DATABASE_URL", "LAVA_EXECUTOR_DATABASE_URL"}
    }
    daemon_environment.update(
        LAVA_ENVIRONMENT="test",
        LAVA_EXECUTOR_DATABASE_URL=executor_url,
        LAVA_EXECUTOR_DATABASE_ROLE=executor_role,
    )
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    key_path = root / "key"
    provision_key(key_path)
    key = load_key(key_path)
    processes = []

    def start():
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "lava.executor",
                "--socket",
                str(root / "sock"),
                "--key-file",
                str(key_path),
            ],
            env=daemon_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)

        # Use an authenticated response, not stale socket existence, as readiness.
        def ready():
            if process.poll() is not None:
                pytest.fail("Executor daemon exited during startup")
            if not (root / "sock").exists():
                return False
            import socket

            try:
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.settimeout(0.2)
                    connection.connect(str(root / "sock"))
                return True
            except OSError:
                return False

        until(ready)
        return process

    start()
    yield engine, req, root, key, start, processes
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
    with Session(engine) as db:
        job = db.get(DeploymentJob, req.job_id)
        job.status = "failed"
        db.commit()


def send(daemon, operation, req=None):
    _, original, root, key, *_ = daemon
    value = replace(
        req or original,
        operation=operation,
        nonce=secrets.token_hex(32),
        expires_at=int(time.time()) + 30,
    )
    return exchange(root / "sock", key, value)


def test_completed_fixture_reply_has_verified_digest(claimed, tmp_path, monkeypatch):  # noqa: F811
    engine, request = claimed
    digest = "sha256:" + "a" * 64
    with Session(engine) as db:
        execution = authorize(db, request, kind="fixture-build")
        execution.status = "COMPLETED"
        execution.image_digest = digest
        db.commit()
    service = ExecutorService(engine, tmp_path / "spool", kind="fixture-build")
    monkeypatch.setattr(service, "scan_one", lambda _: "COMPLETED")
    response = service.handle(replace(request, operation="result", nonce=uuid4().hex * 2))
    assert response == {
        "execution_id": request.execution_id,
        "status": "COMPLETED",
        "mode": "fixture-build",
        "image_digest": digest,
    }


def test_real_daemon_start_result_and_duplicate_submission(daemon):
    engine, req, root, *_ = daemon
    assert send(daemon, "start")["status"] == "RUNNING"
    assert send(daemon, "start")["status"] == "RUNNING"
    until(lambda: send(daemon, "status").get("status") == "COMPLETED")
    assert send(daemon, "result")["status"] == "COMPLETED"
    assert send(daemon, "start")["status"] == "COMPLETED"
    with Session(engine) as db:
        assert (
            len(list(db.scalars(select(BuildExecution).where(BuildExecution.job_id == req.job_id))))
            == 1
        )
    assert (
        json.loads((root / "processes" / req.execution_id / "result.json").read_text())["status"]
        == "COMPLETED"
    )


def test_real_daemon_cancel_is_durable_and_idempotent(daemon):
    _, req, root, *_ = daemon
    assert send(daemon, "start")["status"] == "RUNNING"
    assert send(daemon, "cancel")["status"] == "CANCELLED"
    assert send(daemon, "cancel")["status"] == "CANCELLED"
    assert send(daemon, "status")["status"] == "CANCELLED"
    assert (
        json.loads((root / "processes" / req.execution_id / "result.json").read_text())["status"]
        == "CANCELLED"
    )


def test_executor_crash_restart_recovers_receipt_without_duplicate(daemon):
    _, req, root, _, start, processes = daemon
    send(daemon, "start")
    processes[-1].kill()
    processes[-1].wait(timeout=2)
    until(lambda: (root / "processes" / req.execution_id / "result.json").exists())
    start()
    assert send(daemon, "status")["status"] == "COMPLETED"
    assert send(daemon, "start")["status"] == "COMPLETED"


def test_expired_lease_stops_real_process_and_rejects_late_success(daemon):
    engine, req, root, *_ = daemon
    send(daemon, "start")
    with Session(engine) as db:
        job = db.get(DeploymentJob, req.job_id)
        job.leased_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    until(lambda: (root / "processes" / req.execution_id / "result.json").exists())
    assert (
        json.loads((root / "processes" / req.execution_id / "result.json").read_text())["status"]
        == "CANCELLED"
    )
    assert send(daemon, "result") == {"error": "rejected"}


@pytest.mark.parametrize("cancel", [False, True])
def test_worker_socket_process_database_lifecycle(daemon, cancel):
    engine, req, root, key, *_ = daemon
    with Session(engine) as db:
        job = db.get(DeploymentJob, req.job_id)
        job.status = "queued"
        job.priority = 100000
        db.add(DeploymentEvent(deployment_id=req.deployment_id, sequence=0, to_status="queued"))
        db.commit()
    errors = []

    def worker():
        try:
            with Session(engine) as db:
                DeploymentWorker(db, "e2e-worker", heartbeat_interval=0.1).process_once(
                    executor_factory=lambda job, deployment, token: SocketExecutor(
                        root / "sock", key, job, deployment, token, "python"
                    )
                )
        except Exception as error:
            errors.append(type(error).__name__)

    thread = threading.Thread(target=worker)
    thread.start()

    def execution_started():
        with Session(engine) as db:
            return db.scalar(select(BuildExecution).where(BuildExecution.job_id == req.job_id))

    execution = until(execution_started)
    if cancel:
        with Session(engine) as db:
            DeploymentWorker(db, "cancel-controller").cancel(req.job_id)
    thread.join(timeout=8)
    assert not thread.is_alive()
    assert errors == []
    with Session(engine) as db:
        job = db.get(DeploymentJob, req.job_id)
        deployment = db.get(Deployment, req.deployment_id)
        assert job.status == ("cancelled" if cancel else "succeeded")
        # This is explicitly the existing simulated lifecycle, not an image build.
        assert deployment.status == ("cancelled" if cancel else "active")
        assert db.get(BuildExecution, execution.id).status == (
            "CANCELLED" if cancel else "COMPLETED"
        )


def test_real_worker_death_and_restart_adopts_completed_receipt(daemon):
    engine, req, root, *_ = daemon
    with Session(engine) as db:
        job = db.get(DeploymentJob, req.job_id)
        job.status = "queued"
        job.priority = 100000
        db.add(DeploymentEvent(deployment_id=req.deployment_id, sequence=0, to_status="queued"))
        db.commit()
    environment = {
        **os.environ,
        "LAVA_ENVIRONMENT": "test",
        "LAVA_WORKER_EXECUTOR_MODE": "controlled-probe",
        "LAVA_EXECUTOR_SOCKET": str(root / "sock"),
        "LAVA_EXECUTOR_KEY_FILE": str(root / "key"),
        "LAVA_WORKER_LEASE_SECONDS": "4",
        "LAVA_WORKER_HEARTBEAT_INTERVAL_SECONDS": "1",
    }

    def start_worker():
        return subprocess.Popen(
            [sys.executable, "-m", "lava.worker"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    first = start_worker()
    try:

        def running():
            with Session(engine) as db:
                return db.scalar(select(BuildExecution).where(BuildExecution.job_id == req.job_id))

        execution = until(running)
        first.kill()
        first.wait(timeout=2)
        receipt = root / "processes" / execution.id / "result.json"
        until(receipt.exists)
        assert json.loads(receipt.read_text())["status"] == "COMPLETED"
        second = start_worker()
        try:

            def acknowledged():
                with Session(engine) as db:
                    return db.get(DeploymentJob, req.job_id).status == "succeeded"

            until(acknowledged, seconds=10)
            with Session(engine) as db:
                identities = list(
                    db.scalars(select(BuildExecution.id).where(BuildExecution.job_id == req.job_id))
                )
            assert sum((root / "processes" / identity).exists() for identity in identities) == 1
        finally:
            second.terminate()
            second.wait(timeout=5)
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=2)


def test_database_disconnect_stops_owned_work_before_daemon_restart(daemon):
    from sqlalchemy import text

    engine, req, root, _, start, processes = daemon
    send(daemon, "start")
    with engine.begin() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE application_name = 'lava-executor-runtime' "
                "AND datname = current_database()"
            )
        )
    until(lambda: processes[-1].poll() is not None, seconds=8)
    receipt = root / "processes" / req.execution_id / "result.json"
    until(receipt.exists)
    assert json.loads(receipt.read_text())["status"] == "CANCELLED"
    start()
    assert send(daemon, "status")["status"] == "CANCELLED"


def test_duplicate_daemon_cannot_modify_active_execution(daemon, executor_database):
    _, req, root, *_ = daemon
    send(daemon, "start")
    other = root / "other"
    other.mkdir(mode=0o700)
    provision_key(other / "key")
    duplicate = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "lava.executor",
            "--socket",
            str(other / "sock"),
            "--key-file",
            str(other / "key"),
        ],
        env={
            **os.environ,
            "LAVA_ENVIRONMENT": "test",
            "LAVA_EXECUTOR_DATABASE_URL": executor_database[0],
            "LAVA_EXECUTOR_DATABASE_ROLE": executor_database[1],
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert duplicate.wait(timeout=5) != 0
    assert send(daemon, "status")["status"] in {"RUNNING", "COMPLETED"}


def test_executor_runtime_role_cannot_read_accounts_or_mutate_leases(executor_database):
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import ProgrammingError

    engine = create_engine(executor_database[0])
    try:
        for statement in (
            "SELECT * FROM users LIMIT 1",
            "UPDATE deployment_jobs SET lease_generation = lease_generation + 1",
            "CREATE TABLE forbidden_executor_table(id integer)",
        ):
            with engine.begin() as connection:
                with pytest.raises(ProgrammingError):
                    connection.execute(text(statement))
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == executor_database[1]
            connection.execute(text("SELECT id FROM build_executions LIMIT 1"))
    finally:
        engine.dispose()
