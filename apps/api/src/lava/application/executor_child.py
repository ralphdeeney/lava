"""Bounded owned process-group runner with a durable completion receipt.

Only the executor creates specs in its private spool; no socket payload is used
as a command. Cancellation uses an owned marker rather than a recovered PID.
"""

import json
import os
import re
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path


def stop_owned_buildkit() -> bool:
    """Stop this disposable executor's sole builder before declaring termination."""
    try:
        stopped = subprocess.run(
            ["docker", "buildx", "stop", "lava-fixtures"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        if stopped.returncode:
            return False
        active = subprocess.run(
            ["docker", "ps", "-q", "--filter", "name=^/buildx_buildkit_lava-fixtures0$"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return active.returncode == 0 and not active.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False


def write_receipt(
    directory: Path,
    status: str,
    spec: dict,
    failure_code: str | None = None,
    failure_detail: str | None = None,
) -> None:
    temporary = directory / "result.tmp"
    with temporary.open("x") as stream:
        receipt = {
            "status": status,
            "execution_id": directory.name,
            "receipt_nonce": spec["receipt_nonce"],
        }
        if failure_code is not None:
            receipt["failure_code"] = failure_code
        if failure_detail:
            receipt["failure_detail"] = failure_detail[-4000:]
        if status == "COMPLETED" and spec.get("kind") == "fixture-build":
            receipt["artifact"] = json.loads((directory / "artifact.json").read_text())
        json.dump(receipt, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(directory / "result.json")
    fd = os.open(directory, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> None:
    directory = Path(sys.argv[1])
    spec = json.loads((directory / "spec.json").read_text())
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (3600, 3600))
    stop = False

    def cancel(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    stderr_path = directory / "stderr.log"
    stderr_stream = stderr_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        spec["argv"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=stderr_stream,
        env={
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            **(
                {
                    name: os.environ[name]
                    for name in (
                        "PATH",
                        "HTTPS_PROXY",
                        "HTTP_PROXY",
                        "SSL_CERT_FILE",
                        "GITHUB_ACTIONS",
                        "GITHUB_EVENT_NAME",
                        "GITHUB_REF",
                        "GITHUB_REPOSITORY",
                        "GITHUB_SHA",
                        "LAVA_PROMOTED_SOURCE_SHA",
                        "HOME",
                        "DOCKER_HOST",
                        "DOCKER_CONFIG",
                    )
                    if name in os.environ
                }
                if spec.get("kind") == "fixture-build"
                else {}
            ),
        },
        close_fds=True,
    )
    deadline = time.monotonic() + spec["timeout"]
    status = "UNKNOWN"
    failure_code = None
    failure_detail = None
    try:
        while True:
            # WNOWAIT reserves the leader PID until the entire owned group is killed.
            ended = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if stop or (directory / "cancel").exists():
                status = "CANCELLED"
                failure_code = "cancelled"
                break
            if time.monotonic() >= deadline:
                status = "FAILED"
                failure_code = "timeout"
                break
            if ended is not None:
                status = "COMPLETED" if ended.si_status == 0 else "FAILED"
                if status == "FAILED":
                    failure_code = "process_failed"
                break
            time.sleep(0.05)
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            time.sleep(0.1)
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
        stderr_stream.close()
        if status == "FAILED":
            failure_detail = re.sub(
                r"(?i)(password|secret|token|authorization|cookie)\s*[=:]\s*\S+",
                r"\1=<redacted>",
                stderr_path.read_text(errors="replace")[-4000:],
            ).strip()
        if spec.get("kind") == "fixture-build" and status != "COMPLETED":
            # The Docker client exit alone does not terminate daemon-side work.
            # This builder is created solely for this disposable verifier.
            if not stop_owned_buildkit():
                status = "UNKNOWN"
                failure_code = "builder_stop_unconfirmed"
        write_receipt(directory, status, spec, failure_code, failure_detail)


if __name__ == "__main__":
    main()
