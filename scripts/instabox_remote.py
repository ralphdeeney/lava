"""Bounded VM-side Phase 00 job; receives source, never cloud/GitHub credentials."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from verify_instabox import redact


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    run = args.run_dir.resolve()
    root = Path("/data/lava-ci/runs")
    if run.parent != root or not re.fullmatch(r"\d+-\d+", run.name):
        raise RuntimeError("Invalid owned run directory")
    checkout = run / "checkout"
    if Path(__file__).resolve().parent.parent != checkout:
        raise RuntimeError("Runner must execute from its owned checkout")
    project = "lava-verify-" + hashlib.sha256(run.name.encode()).hexdigest()[:12]
    db = "lava-ci-db-" + run.name
    status = {
        "commit": args.commit,
        "run": run.name,
        "state": "running",
        "pid": os.getpid(),
        "steps": [],
        "machine": "agent-development",
    }
    write_json(run / "status.json", status)
    secrets = [
        value
        for name, value in os.environ.items()
        if re.search(r"TOKEN|PASSWORD|SECRET|API_KEY", name) and value
    ]
    log = run / "diagnostics.log"
    env = os.environ.copy()
    env.update(
        LAVA_CACHE_DIR="/data/lava-ci/cache",
        UV_CACHE_DIR="/data/lava-ci/cache/uv",
        npm_config_cache="/data/lava-ci/cache/npm",
        COMPOSE_PARALLEL_LIMIT="1",
        BUILDX_CONFIG="/data/lava-ci/cache/buildx",
    )
    env["PATH"] = "/data/lava-ci/cache/tools/node_modules/.bin:" + env["PATH"]
    for name in list(env):
        if name.startswith("COMPOSE_") and name != "COMPOSE_PARALLEL_LIMIT":
            env.pop(name)
    for name in ("LAVA_INTEGRATION", "LAVA_TEST_DATABASE_RESET", "LAVA_DATABASE_URL"):
        env.pop(name, None)

    def record(output: str) -> None:
        prior = log.read_text() if log.exists() else ""
        data = redact(prior + output, secrets).encode()[-65536:]
        log.write_bytes(data.decode(errors="ignore").encode())

    def command(
        argv: list[str],
        *,
        cwd: Path = checkout,
        timeout: int = 120,
        extra: dict | None = None,
        check: bool = True,
        record_output: bool = True,
    ) -> str:
        child = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env | (extra or {}),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            output, _ = child.communicate(timeout=timeout)
        except BaseException:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
            raise
        if record_output:
            record(output)
        if check and child.returncode:
            raise RuntimeError(f"Command {argv[0]} exited {child.returncode}")
        return output.strip()

    def step(name: str, argv: list[str], **kwargs) -> str:
        output = command(argv, **kwargs)
        status["steps"].append(name)
        write_json(run / "status.json", status)
        return output

    def interrupted(signum, frame):
        raise TimeoutError(f"Job deadline/signal {signum}")

    signal.signal(signal.SIGALRM, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    lock = Path("/data/lava-ci/machine.lock").open("a")
    acquired = False
    database_started = False
    code = 1
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            raise RuntimeError("Another infrastructure run holds the VM lock") from None
        signal.alarm(1200)
        if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
            raise RuntimeError("Invalid full commit SHA")
        actual = step("exact_commit", ["git", "rev-parse", "HEAD"])
        if actual != args.commit:
            raise RuntimeError("Checkout does not match requested commit")
        status["environment"] = {
            "dockerRoot": command(["docker", "info", "--format", "{{.DockerRootDir}}"]),
            "dataFreeMiB": shutil.disk_usage("/data").free // 1024**2,
            "python": sys.version.split()[0],
            "node": command(["node", "--version"]),
            "compose": command(["docker", "compose", "version", "--short"]),
        }
        if status["environment"]["dockerRoot"] != "/data/docker":
            raise RuntimeError(
                "Unexpected Docker data-root; no storage changes attempted"
            )
        step(
            "storage_and_prerequisites",
            ["python3", "scripts/verify_instabox.py", "--preflight-only"],
        )
        step(
            "bootstrap_lint_unit_frontend",
            ["bash", "scripts/bootstrap.sh"],
            timeout=600,
        )
        # A new disposable DB is independent of the operator's development database.
        import secrets as random_secrets

        password = random_secrets.token_hex(24)
        secrets.append(password)
        config = json.loads(
            command(
                ["docker", "compose", "config", "--format", "json"], record_output=False
            )
        )
        image = config["services"]["db"]["image"]
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                db,
                "--label",
                "lava.ci.run=" + run.name,
                "-e",
                "POSTGRES_PASSWORD=" + password,
                "-e",
                "POSTGRES_DB=lava_test",
                "-p",
                "127.0.0.1::5432",
                image,
            ]
        )
        database_started = True
        for _ in range(30):
            ready = command(
                [
                    "docker",
                    "exec",
                    db,
                    "pg_isready",
                    "-U",
                    "postgres",
                    "-d",
                    "lava_test",
                ],
                check=False,
            )
            if "accepting connections" in ready:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        address = command(["docker", "port", db, "5432"])
        if not re.fullmatch(r"127\.0\.0\.1:\d+", address):
            raise RuntimeError("Unexpected test database binding")
        step(
            "complete_pytest_postgresql",
            [
                "uv",
                "run",
                "--locked",
                "python",
                str(checkout / "scripts/run_pytest.py"),
                "--junit",
                str(checkout / "test-results/instabox-postgresql.xml"),
                "--cwd",
                str(checkout / "apps/api"),
                "--",
                "tests",
            ],
            cwd=checkout / "apps/api",
            extra={
                "LAVA_DATABASE_URL": f"postgresql+psycopg://postgres:{password}@{address}/lava_test",
                "LAVA_INTEGRATION": "1",
                "LAVA_TEST_DATABASE_RESET": "1",
            },
        )
        step(
            "compose_integration",
            ["python3", "scripts/verify_instabox.py", "--project", project],
            timeout=900,
        )
        code = 0
    except (
        RuntimeError,
        OSError,
        ValueError,
        TimeoutError,
        subprocess.TimeoutExpired,
    ) as exc:
        status["error"] = redact(str(exc), secrets)
        record(status["error"] + "\n")
    finally:
        signal.alarm(0)
        if acquired:
            try:
                if database_started:
                    command(["docker", "rm", "-fv", db])
                # Only the known per-run project, never operator services or volumes.
                if (checkout / ".env").exists():
                    command(
                        [
                            "docker",
                            "compose",
                            "-p",
                            project,
                            "down",
                            "--volumes",
                            "--rmi",
                            "local",
                            "--timeout",
                            "15",
                        ],
                        timeout=90,
                    )
                status["steps"].append("owned_resource_cleanup")
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                record("Cleanup failed: " + redact(str(exc), secrets))
                status["error"] = (
                    "Owned resource cleanup needs recovery; no global deletion attempted"
                )
                code = 1
        status.update(state="succeeded" if code == 0 else "failed", exitCode=code)
        # Remove only newly created source/bundle, including its ephemeral .env.
        try:
            shutil.rmtree(checkout)
            (run / "source.bundle").unlink(missing_ok=True)
        except OSError:
            status.update(
                state="failed", exitCode=1, error="Owned checkout cleanup failed"
            )
            code = 1
        write_json(run / "status.json", status)
        lock.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
