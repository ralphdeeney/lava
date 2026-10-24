import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from lava.core.settings import Settings
from lava.main import app, check_database


def test_health_does_not_require_database():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "available,code,status", [(True, 200, "ready"), (False, 503, "unavailable")]
)
def test_readiness(available, code, status):
    app.dependency_overrides[check_database] = lambda: available
    try:
        with TestClient(app) as client:
            response = client.get("/ready")
            assert response.status_code == code
            assert response.json() == {"status": status}
    finally:
        app.dependency_overrides.clear()


def test_settings_redact_credentials():
    settings = Settings(database_url="postgresql+psycopg://user:secret@db/lava")
    assert "secret" not in repr(settings)
    with pytest.raises(ValidationError):
        Settings(database_url="x", environment="invalid")


def test_database_failure_is_unavailable():
    settings = Settings(database_url="postgresql+psycopg://x:x@127.0.0.1:1/x")
    assert check_database(settings) is False


def test_settings_reject_non_postgres_url():
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///local.db")


def test_request_id_and_structured_log(caplog):
    import json
    import logging

    with caplog.at_level(logging.INFO), TestClient(app) as client:
        response = client.get("/health?token=do-not-log")
    events = []
    for record in caplog.records:
        if record.name == "lava.main":
            events.append(json.loads(record.message))
    event = next(item for item in events if item["event"] == "http_request")
    assert event["request_id"] == response.headers["X-Request-ID"]
    assert event["status_code"] == 200
    assert "do-not-log" not in json.dumps(event)
