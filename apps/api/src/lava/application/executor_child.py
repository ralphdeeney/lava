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


def write_receipt(directory: Path, status: str) -> None:
    temporary = directory / "result.tmp"
    with temporary.open("x") as stream:
        json.dump({"status": status}, stream)
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
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
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
        env={"PATH": os.defpath, "LANG": "C.UTF-8"},
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
        write_receipt(directory, status)


if __name__ == "__main__":
    main()
