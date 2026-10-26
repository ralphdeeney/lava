"""Local authenticated executor for controlled fixtures; no Docker privileges required."""

import argparse
import asyncio
import contextlib
import fcntl
import os
import re
import secrets
import signal
import socket
import stat
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from lava.application.executor_authorization import authorize
from lava.application.executor_process import ProcessSupervisor
from lava.application.executor_protocol import ExecutorRequest, sign
from lava.application.executor_recovery import reconcile
from lava.application.executor_transport import ExecutorSocket
from lava.db.base import BuildExecution, BuildRequestNonce, DeploymentJob


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
    def __init__(
        self, engine, spool: Path, kind: str = "controlled-probe", source_root: Path | None = None
    ):
        self.engine = engine
        self.kind = kind
        self.source_root = source_root
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
                    "COMPLETED"
                    if observed == "COMPLETED" and job.cancellation_requested_at is None
                    else "CANCELLED"
                    if observed in {"COMPLETED", "CANCELLED", "FAILED"}
                    else "UNKNOWN"
                )
            else:
                observed = self.supervisor.status(execution_id)
                execution.status = observed
            if execution.status == "COMPLETED" and execution.kind == "fixture-build":
                artifact = self.supervisor.result(execution_id).get("artifact", {})
                digest = artifact.get("image_digest", "")
                if (
                    not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                    or artifact.get("source_commit") != execution.source_commit_sha
                ):
                    execution.status = "UNKNOWN"
                else:
                    execution.image_digest = digest
            execution.updated_at = datetime.now(UTC)
            session.commit()
            return execution.status

    def scan(self) -> None:
        with Session(self.engine) as session:
            expired = (
                select(BuildRequestNonce.nonce_hash)
                .where(BuildRequestNonce.expires_at < datetime.now(UTC) - timedelta(days=1))
                .limit(1000)
            )
            session.execute(
                delete(BuildRequestNonce).where(BuildRequestNonce.nonce_hash.in_(expired))
            )
            session.commit()
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
            execution = authorize(session, request, kind=self.kind)
            created = execution.newly_authorized
            if request.operation == "start" and created and execution.status != "COMPLETED":
                try:
                    if self.kind == "fixture-build":
                        from lava.builds.fixture_toolchain import validate_trusted_source

                        validate_trusted_source(
                            self.source_root, request.source_commit, request.fixture
                        )
                        output = self.supervisor.root / request.execution_id / "artifact.json"
                        argv = [
                            sys.executable,
                            "-m",
                            "lava.builds.fixture_runner",
                            "--root",
                            str(self.source_root),
                            "--commit",
                            request.source_commit,
                            "--fixture",
                            request.fixture,
                            "--output",
                            str(output),
                        ]
                    else:
                        argv = list(PLANS[request.fixture])
                    self.supervisor.start(
                        request.execution_id,
                        argv,
                        timeout=1500 if self.kind == "fixture-build" else 10,
                        kind=self.kind,
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

    info = path.lstat()
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or path.parent.stat().st_mode & 0o077
    ):
        raise PermissionError("Unsafe executor socket identity")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(str(path))
        import struct

        _, uid, _ = struct.unpack(
            "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
        if uid != os.getuid():
            raise PermissionError("Unexpected executor peer")
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


async def serve(
    path: Path, key: bytes, engine, kind: str = "controlled-probe", source_root: Path | None = None
):
    if path.parent.stat().st_mode & 0o077 or path.parent.stat().st_uid != os.getuid():
        raise PermissionError("Executor requires a private owner-controlled directory")
    # Filesystem lock prevents deleting a live socket. Database lock prevents a
    # second executor using a different socket/spool against the same queue.
    lock_fd = os.open(path.parent / "executor.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    database_lock = engine.connect()
    service = ExecutorService(engine, path.parent / "processes", kind, source_root)
    stop = asyncio.Event()
    acquired = False
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not database_lock.scalar(text("SELECT pg_try_advisory_lock(71502201)")):
            raise RuntimeError("Executor already active for this database")
        acquired = True
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
                        database_lock.scalar(text("SELECT 1"))
                        service.scan()
                    except Exception:
                        # Fail closed on uncertain DB ownership; do not publish success.
                        service.supervisor.shutdown()
                        stop.set()
    finally:
        if acquired:
            with contextlib.suppress(Exception):
                service.shutdown()
            with contextlib.suppress(Exception):
                database_lock.execute(text("SELECT pg_advisory_unlock(71502201)"))
        database_lock.close()
        os.close(lock_fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--provision-key", action="store_true")
    parser.add_argument(
        "--mode", choices=("controlled-probe", "fixture-build"), default="controlled-probe"
    )
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    if args.provision_key:
        provision_key(args.key_file)
        return
    from lava.core.settings import ExecutorSettings

    settings = ExecutorSettings()
    if args.mode == "fixture-build":
        from lava.builds.fixture_toolchain import validate_trusted_source

        if args.source_root is None:
            raise RuntimeError("Fixture builds require an audited checkout")
        validate_trusted_source(args.source_root, os.environ.get("GITHUB_SHA", ""), "python")
    if args.mode == "controlled-probe" and os.environ.get("LAVA_ENVIRONMENT") != "test":
        raise RuntimeError("Controlled executor probes require the test environment")
    engine = create_engine(
        settings.database_url.get_secret_value(),
        connect_args={
            "connect_timeout": 3,
            "options": "-c statement_timeout=3000 -c lock_timeout=2000",
            "application_name": "lava-executor-runtime",
        },
    )
    try:
        with engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, "
                    "rolreplication, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            if connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_auth_members "
                    "WHERE member = current_user::regrole::oid)"
                )
            ):
                raise PermissionError("Executor role must not inherit other roles")
            if role[0] != settings.database_role or any(role[1:]):
                raise PermissionError("Unsafe executor database role")
            if connection.scalar(
                text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
            ):
                raise PermissionError("Executor must not own the schema")
            if connection.scalar(
                text("SELECT has_table_privilege(current_user, 'users', 'SELECT')")
            ):
                raise PermissionError("Executor must not read account tables")
        asyncio.run(
            serve(args.socket, load_key(args.key_file), engine, args.mode, args.source_root)
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
