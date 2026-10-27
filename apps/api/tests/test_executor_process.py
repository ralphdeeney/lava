import json
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
    receipt = json.loads((supervisor.root / identity / "result.json").read_text())
    assert receipt["failure_code"] == "cancelled"


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
        receipt = json.loads((supervisor.root / identity / "result.json").read_text())
        assert receipt["failure_code"] == "timeout"
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


def test_failed_process_has_distinct_durable_reason(tmp_path):
    import sys

    supervisor = ProcessSupervisor(tmp_path / "spool")
    identity = str(uuid4())
    supervisor.start(identity, [sys.executable, "-c", "raise SystemExit(42)"], timeout=3)
    deadline = time.monotonic() + 3
    while supervisor.status(identity) == "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert supervisor.status(identity) == "FAILED"
    receipt = json.loads((supervisor.root / identity / "result.json").read_text())
    assert receipt["failure_code"] == "process_failed"


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


def test_fixture_child_receives_only_explicit_promotion_identity(tmp_path, monkeypatch):
    import sys

    promoted = "a" * 40
    monkeypatch.setenv("LAVA_PROMOTED_SOURCE_SHA", promoted)
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    monkeypatch.setenv("LAVA_DATABASE_URL", "must-not-reach-build")
    supervisor = ProcessSupervisor(tmp_path / "spool")
    identity = str(uuid4())
    artifact = supervisor.root / identity / "artifact.json"
    script = (
        "import json,os,sys; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(json.dumps({"
        "'promotion':os.environ.get('LAVA_PROMOTED_SOURCE_SHA'),"
        "'database':os.environ.get('LAVA_DATABASE_URL')}))"
    )
    supervisor.start(
        identity, [sys.executable, "-c", script, str(artifact)], timeout=5, kind="fixture-build"
    )
    deadline = time.monotonic() + 5
    while supervisor.status(identity) == "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert supervisor.status(identity) == "COMPLETED"
    result = supervisor.result(identity)["artifact"]
    assert result == {"promotion": promoted, "database": None}


def test_builder_shutdown_requires_observed_owned_container_exit(monkeypatch):
    import subprocess

    from lava.application.executor_child import stop_owned_buildkit

    commands = []

    def completed(argv, **_):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"" if len(commands) == 2 else None)

    monkeypatch.setattr("lava.application.executor_child.subprocess.run", completed)
    assert stop_owned_buildkit()
    assert commands == [
        ["docker", "buildx", "stop", "lava-fixtures"],
        ["docker", "ps", "-q", "--filter", "name=^/buildx_buildkit_lava-fixtures0$"],
    ]
    commands.clear()

    def still_running(argv, **_):
        commands.append(argv)
        output = b"container" if len(commands) == 2 else None
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    monkeypatch.setattr("lava.application.executor_child.subprocess.run", still_running)
    assert not stop_owned_buildkit()
