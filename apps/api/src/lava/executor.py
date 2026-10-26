"""Local authenticated executor for controlled fixtures; no Docker privileges required."""

import argparse
import asyncio
import contextlib
import fcntl
import os
import secrets
import signal
import socket
import stat
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from lava.application.executor_authorization import authorize
from lava.application.executor_process import ProcessSupervisor
from lava.application.executor_protocol import ExecutorRequest, sign
from lava.application.executor_recovery import reconcile
from lava.application.executor_transport import ExecutorSocket
from lava.db.base import BuildExecution, DeploymentJob


def load_key(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError("Executor key requires owner-only access")
        key = os.read(fd, 33)
        if len(key) != 32:
            raise ValueError("Executor key must contain exactly 32 random bytes")
        return key
    finally:
        os.close(fd)


def provision_key(path: Path) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, secrets.token_bytes(32))
        os.fsync(fd)
    finally:
        os.close(fd)


# Controlled process probes only. These are not image builds or deployment success.
PLANS = {name: ("/bin/sleep", "2") for name in ("python", "node", "go")}


class ExecutorService:
    def __init__(self, engine, spool: Path):
        self.engine = engine
        self.supervisor = ProcessSupervisor(spool)

    def scan_one(self, execution_id: str) -> str:
        with Session(self.engine) as session:
            identity = session.get(BuildExecution, execution_id)
            if identity is None:
                return "UNKNOWN"
            job = session.scalar(
                select(DeploymentJob).where(DeploymentJob.id == identity.job_id).with_for_update()
            )
            execution = session.scalar(
                select(BuildExecution).where(BuildExecution.id == execution_id).with_for_update()
            )
            if execution.status in {"COMPLETED", "CANCELLED", "FAILED"}:
                return execution.status
            stale = (
                job.status != "running"
                or job.lease_generation != execution.claim_generation
                or job.leased_until is None
                or job.leased_until <= datetime.now(UTC)
            )
            if stale or job.cancellation_requested_at is not None:
                observed = self.supervisor.cancel(execution_id)
                execution.status = (
                    "CANCELLED" if observed in {"COMPLETED", "CANCELLED", "FAILED"} else "UNKNOWN"
                )
            else:
                observed = self.supervisor.status(execution_id)
                execution.status = observed
            execution.updated_at = datetime.now(UTC)
            session.commit()
            return execution.status

    def scan(self) -> None:
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    select(BuildExecution.id)
                    .where(BuildExecution.status.in_(["RUNNING", "UNKNOWN"]))
                    .order_by(BuildExecution.updated_at)
                    .limit(100)
                )
            )
        for execution_id in ids:
            self.scan_one(execution_id)

    def handle(self, request: ExecutorRequest) -> dict:
        # Only one external process at a time on this lightweight executor.
        if request.operation == "start":
            with Session(self.engine) as capacity:
                other = capacity.scalar(
                    select(BuildExecution.id)
                    .where(
                        BuildExecution.status == "RUNNING",
                        BuildExecution.id != request.execution_id,
                    )
                    .limit(1)
                )
                if other is not None:
                    raise PermissionError("Executor capacity exhausted")
        with Session(self.engine) as session:
            execution = authorize(session, request)
            created = execution.newly_authorized
            if request.operation == "start" and created:
                try:
                    self.supervisor.start(
                        request.execution_id, list(PLANS[request.fixture]), timeout=10
                    )
                    reconcile(session, request.execution_id, "RUNNING")
                except Exception:
                    self.supervisor.cancel(request.execution_id)
                    raise
            elif request.operation == "cancel":
                job = session.scalar(
                    select(DeploymentJob)
                    .where(DeploymentJob.id == request.job_id)
                    .with_for_update()
                )
                if job.lease_generation != request.claim_generation:
                    raise PermissionError("Lease reassigned")
                job.cancellation_requested_at = datetime.now(UTC)
                session.commit()
        status = self.scan_one(request.execution_id)
        return {"execution_id": request.execution_id, "status": status, "mode": "controlled-probe"}

    def shutdown(self):
        self.supervisor.shutdown()
        self.scan()


def exchange(path: Path, key: bytes, request: ExecutorRequest) -> dict:
    import json

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(str(path))
        connection.sendall(
            (
                json.dumps({"request": asdict(request), "signature": sign(request, key)}) + "\n"
            ).encode()
        )
        data = bytearray()
        while not data.endswith(b"\n"):
            part = connection.recv(4096 - len(data))
            if not part or len(data) + len(part) >= 4096:
                raise ConnectionError("Invalid executor response")
            data.extend(part)
        return json.loads(data)


async def serve(path: Path, key: bytes, engine):
    if path.parent.stat().st_mode & 0o077 or path.parent.stat().st_uid != os.getuid():
        raise PermissionError("Executor requires a private owner-controlled directory")
    # Filesystem lock prevents deleting a live socket. Database lock prevents a
    # second executor using a different socket/spool against the same queue.
    lock_fd = os.open(path.parent / "executor.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    database_lock = engine.connect()
    service = ExecutorService(engine, path.parent / "processes")
    stop = asyncio.Event()
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not database_lock.scalar(text("SELECT pg_try_advisory_lock(71502201)")):
            raise RuntimeError("Executor already active for this database")
        if path.exists():
            if not stat.S_ISSOCK(path.lstat().st_mode) or path.lstat().st_uid != os.getuid():
                raise PermissionError("Unsafe existing socket")
            path.unlink()
        service.scan()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        async with ExecutorSocket(path, key, service.handle):
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=0.5)
                except TimeoutError:
                    try:
                        service.scan()
                    except Exception:
                        # Fail closed on uncertain DB ownership; do not publish success.
                        service.supervisor.shutdown()
    finally:
        with contextlib.suppress(Exception):
            service.shutdown()
        database_lock.close()
        os.close(lock_fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--provision-key", action="store_true")
    args = parser.parse_args()
    if args.provision_key:
        provision_key(args.key_file)
        return
    from lava.core.settings import get_settings

    settings = get_settings()
    if settings.environment != "test":
        raise RuntimeError("Controlled executor probes require the test environment")
    engine = create_engine(
        settings.database_url.get_secret_value(),
        connect_args={
            "connect_timeout": 3,
            "options": "-c statement_timeout=3000 -c lock_timeout=2000",
        },
    )
    try:
        asyncio.run(serve(args.socket, load_key(args.key_file), engine))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
