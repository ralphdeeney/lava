"""Worker behavior while an external build is being cancelled or reconciled."""

from itertools import count
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lava.application.executor_client import ExecutionUncertain, SocketExecutor


def fixture_client(tmp_path):
    job = SimpleNamespace(id=str(uuid4()), lease_generation=1, lease_owner="worker")
    deployment = SimpleNamespace(
        id=str(uuid4()), source_commit_sha="a" * 40, configuration_revision=1
    )
    return SocketExecutor(
        tmp_path / "sock", b"x" * 32, job, deployment, "1.token", "python", mode="fixture-build"
    )


def test_unknown_during_cancellation_waits_for_proven_termination(tmp_path, monkeypatch):
    client = fixture_client(tmp_path)
    replies = iter(("RUNNING", "UNKNOWN", "UNKNOWN", "CANCELLED"))
    operations = []

    def send(operation):
        operations.append(operation)
        return {"status": next(replies)}

    checks = iter((False, True, True, True))
    monkeypatch.setattr(client, "send", send)
    monkeypatch.setattr("lava.application.executor_client.time.sleep", lambda _: None)
    assert client.run(lambda: next(checks)) == "cancelled"
    assert operations == ["start", "cancel", "status", "status"]


def test_unknown_external_outcome_never_becomes_success(tmp_path, monkeypatch):
    client = fixture_client(tmp_path)
    clock = count()
    monkeypatch.setattr("lava.application.executor_client.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("lava.application.executor_client.time.sleep", lambda _: None)
    monkeypatch.setattr(client, "send", lambda _: {"status": "UNKNOWN"})
    with pytest.raises(ExecutionUncertain, match="unknown"):
        client.run(lambda: False)
