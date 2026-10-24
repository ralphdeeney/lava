"""Protocol/safety tests are mocks; real VM evidence is required separately."""

import io
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

with patch.object(sys, "path", [str(Path(__file__).resolve().parents[3] / "scripts"), *sys.path]):
    import instabox_ci as api


def client():
    return api.Client("test-key-not-a-real-credential", "m_test")


def result():
    return {"stdout": "ok", "stderr": "", "exitCode": 0, "timedOut": False, "truncated": False}


def test_unknown_exec_transport_failure_is_not_replayed(monkeypatch):
    instance = client()
    calls = []

    def unavailable(request, **kwargs):
        calls.append(request)
        raise urllib.error.URLError("connection lost")

    instance.opener = SimpleNamespace(open=unavailable)
    with pytest.raises(RuntimeError, match="unsafe replay refused"):
        instance.execute("some workload")
    assert len(calls) == 1


def test_explicit_retryable_rejection_respects_retry_after(monkeypatch):
    instance = client()
    calls = []
    delays = []

    def open_request(request, **kwargs):
        calls.append(request)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "busy",
                {"Retry-After": "7"},
                io.BytesIO(
                    json.dumps({"error": {"code": "quota_exceeded", "retryable": True}}).encode()
                ),
            )
        return io.BytesIO(json.dumps(result()).encode())

    monkeypatch.setattr(api.time, "sleep", delays.append)
    instance.opener = SimpleNamespace(open=open_request)
    assert instance.execute("some workload") == "ok"
    assert len(calls) == 2
    assert delays == [7]


def test_nonretryable_exec_failure_is_not_replayed():
    instance = client()
    calls = []

    def unavailable(request, **kwargs):
        calls.append(request)
        raise urllib.error.HTTPError(
            request.full_url,
            503,
            "unavailable",
            {},
            io.BytesIO(b'{"error":{"code":"host_unavailable","retryable":false}}'),
        )

    instance.opener = SimpleNamespace(open=unavailable)
    with pytest.raises(api.APIError):
        instance.execute("some workload")
    assert len(calls) == 1


def test_retry_after_beyond_budget_is_not_shortened(monkeypatch):
    instance = client()
    delays = []

    def unavailable(request, **kwargs):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "busy",
            {"Retry-After": "120"},
            io.BytesIO(b'{"error":{"retryable":true}}'),
        )

    monkeypatch.setattr(api.time, "sleep", delays.append)
    instance.opener = SimpleNamespace(open=unavailable)
    with pytest.raises(api.APIError):
        instance.execute("some workload")
    assert not delays


@pytest.mark.parametrize(
    "patches",
    [
        {"name": "unrelated"},
        {"free": False},
        {"free": None},
        {"cooldownUntil": "2099-01-01T00:00:00Z"},
        {"maxRunMinutes": 0},
        {"state": "stopped"},
    ],
)
def test_machine_guards_precede_workload(monkeypatch, patches):
    instance = client()
    machine = {
        "name": "agent-development",
        "free": True,
        "state": "running",
        "runtime": {"ready": True},
        **patches,
    }
    calls = []

    def call(method, path, *args, **kwargs):
        calls.append(method)
        return machine

    monkeypatch.setattr(instance, "call", call)
    with pytest.raises(RuntimeError):
        instance.ready(allow_resume=False, run_id="123-1")
    assert calls == ["GET"]


def test_manual_resume_is_authorized_idempotent_and_polled(monkeypatch):
    instance = client()
    calls = []
    state = {"name": "agent-development", "free": True, "state": "suspended"}

    def call(method, path, *args, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/resume"):
            state.update(state="running", runtime={"ready": True})
            return {"id": "op_test"}
        if "/operations/" in path:
            return {"state": "succeeded"}
        return dict(state)

    monkeypatch.setattr(instance, "call", call)
    assert instance.ready(allow_resume=True, run_id="123-1")["state"] == "running"
    resume = next(item for item in calls if item[1].endswith("/resume"))
    assert resume[2]["idempotency"]
    assert any("/operations/op_test?wait=25s" in item[1] for item in calls)


@pytest.mark.parametrize("changes", [{"exitCode": 1}, {"timedOut": True}, {"truncated": True}])
def test_remote_result_cannot_be_misreported_as_success(monkeypatch, changes):
    instance = client()
    monkeypatch.setattr(instance, "call", lambda *args, **kwargs: result() | changes)
    with pytest.raises(RuntimeError, match="Remote API command failed"):
        instance.execute("workload")


def test_api_redirect_cannot_forward_authentication():
    with pytest.raises(RuntimeError, match="redirects are refused"):
        api.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")


def test_failed_resume_operation_is_not_retried(monkeypatch):
    instance = client()
    calls = []

    def call(method, path, *args, **kwargs):
        calls.append(path)
        if path.endswith("/resume"):
            return {"id": "op_failed"}
        if "/operations/" in path:
            return {"state": "failed"}
        return {"name": "agent-development", "free": True, "state": "suspended"}

    monkeypatch.setattr(instance, "call", call)
    with pytest.raises(RuntimeError, match="Authorized resume operation failed"):
        instance.ready(allow_resume=True, run_id="123-1")
    assert sum(path.endswith("/resume") for path in calls) == 1
