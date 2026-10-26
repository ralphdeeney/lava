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
        time.sleep(0.2)
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
