import time
from uuid import uuid4

import pytest

from lava.application.executor_process import ProcessSupervisor


def test_cancel_stops_owned_process_and_child():
    supervisor = ProcessSupervisor()
    identity = str(uuid4())
    process = supervisor.start(
        identity,
        [
            "python",
            "-c",
            "import subprocess,time; subprocess.Popen(['sleep','30']); time.sleep(30)",
        ],
        timeout=35,
    )
    assert process.poll() is None
    assert supervisor.cancel(identity) == "CANCELLED"
    assert process.poll() is not None
    assert supervisor.cancel(identity) == "CANCELLED"


def test_timeout_and_unrelated_process_survive():
    import subprocess

    unrelated = subprocess.Popen(["sleep", "10"])
    try:
        supervisor = ProcessSupervisor()
        identity = str(uuid4())
        supervisor.start(identity, ["sleep", "10"], timeout=0.1)
        deadline = time.monotonic() + 3
        while supervisor.status(identity) == "RUNNING" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert supervisor.status(identity) == "FAILED"
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=2)


def test_duplicate_execution_identity_is_rejected():
    supervisor = ProcessSupervisor()
    identity = str(uuid4())
    supervisor.start(identity, ["sleep", "10"], timeout=20)
    try:
        with pytest.raises(ValueError):
            supervisor.start(identity, ["sleep", "10"], timeout=20)
    finally:
        supervisor.cancel(identity)


def test_forced_group_cleanup_stops_term_ignoring_child(tmp_path):
    import os
    import sys

    pid_file = tmp_path / "child.pid"
    child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    parent = (
        "import subprocess,time; from pathlib import Path; "
        f"p=subprocess.Popen([{sys.executable!r}, '-c', {child!r}]); "
        f"Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    supervisor = ProcessSupervisor(tmp_path / "spool")
    identity = str(uuid4())
    supervisor.start(identity, [sys.executable, "-c", parent], timeout=35)
    deadline = time.monotonic() + 3
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_file.exists()
    pid = int(pid_file.read_text())
    assert supervisor.cancel(identity) == "CANCELLED"
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            state = open(f"/proc/{pid}/stat").read().split()[2]
        except FileNotFoundError:
            break
        if state == "Z":
            break
        time.sleep(0.02)
    else:
        pytest.fail("Owned child remained alive after forced group cancellation")
    assert os.getpid() != pid


def test_receipt_survives_supervisor_restart_and_is_not_executed_twice(tmp_path):
    supervisor = ProcessSupervisor(tmp_path / "spool")
    identity = str(uuid4())
    supervisor.start(identity, ["sleep", "0.1"], timeout=3)
    restarted = ProcessSupervisor(tmp_path / "spool")
    deadline = time.monotonic() + 3
    while restarted.status(identity) == "UNKNOWN" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert restarted.status(identity) == "COMPLETED"
    with pytest.raises(ValueError):
        restarted.start(identity, ["sleep", "0.1"], timeout=3)
    supervisor.shutdown()
