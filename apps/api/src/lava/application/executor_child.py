"""Bounded owned process-group runner with a durable completion receipt.

Only the executor creates specs in its private spool; no socket payload is used
as a command. Cancellation uses an owned marker rather than a recovered PID.
"""

import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path


def write_receipt(directory: Path, status: str, spec: dict) -> None:
    temporary = directory / "result.tmp"
    with temporary.open("x") as stream:
        receipt = {
            "status": status,
            "execution_id": directory.name,
            "receipt_nonce": spec["receipt_nonce"],
        }
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
    process = subprocess.Popen(
        spec["argv"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
    try:
        while True:
            # WNOWAIT reserves the leader PID until the entire owned group is killed.
            ended = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if stop or (directory / "cancel").exists():
                status = "CANCELLED"
                break
            if time.monotonic() >= deadline:
                status = "FAILED"
                break
            if ended is not None:
                status = "COMPLETED" if ended.si_status == 0 else "FAILED"
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
        if spec.get("kind") == "fixture-build" and status != "COMPLETED":
            # Killing the client cannot prove daemon-side build termination.
            status = "UNKNOWN"
        write_receipt(directory, status, spec)


if __name__ == "__main__":
    main()
