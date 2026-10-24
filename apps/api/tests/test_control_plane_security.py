"""Independent ownership/authentication attacks against disposable real PostgreSQL."""

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from test_control_plane import control_plane as control_plane
from test_control_plane import create_project, create_service

from lava.auth.credentials import issue_credential, revoke_credential
from lava.db.base import LEGACY_OWNER_ID, ApiCredential, Project, Service, User

pytestmark = pytest.mark.integration


def test_unauthenticated_projects_are_denied(control_plane):
    fixture = control_plane
    response = fixture.client.get("/projects")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Authentication required"}
    }


@pytest.mark.parametrize(
    "authorization",
    [
        "",
        "Basic dXNlcjpwYXNz",
        "Bearer",
        "Bearer invalid",
        "Bearer lava_" + "x" * 42,
        "Bearer lava_" + "x" * 44,
    ],
)
def test_invalid_authorization_never_establishes_identity(control_plane, authorization):
    response = control_plane.client.get("/projects", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_unknown_well_formed_bearer_is_rejected(control_plane):
    candidate = "lava_" + secrets.token_urlsafe(32)
    response = control_plane.client.get(
        "/projects", headers={"Authorization": "Bearer " + candidate}
    )
    assert response.status_code == 401
    assert candidate not in response.text


def test_identity_headers_query_and_cookies_do_not_authenticate(control_plane):
    fixture = control_plane
    fixture.client.cookies.set("lava_session", fixture.token_a)
    response = fixture.client.get(
        "/projects?user_id=" + fixture.user_a.id,
        headers={"X-User-ID": fixture.user_a.id, "X-Owner-ID": fixture.user_a.id},
    )
    assert response.status_code == 401


def test_client_identity_cannot_override_authenticated_owner(control_plane):
    fixture = control_plane
    headers = fixture.headers_a | {"X-User-ID": fixture.user_b.id, "X-Owner-ID": fixture.user_b.id}
    created = fixture.client.post("/projects", headers=headers, json={"name": "owned-by-principal"})
    assert created.status_code == 201
    assert created.json()["owner_id"] == fixture.user_a.id
    forged = fixture.client.post(
        "/projects",
        headers=fixture.headers_a,
        json={"name": "forged-owner", "owner_id": fixture.user_b.id},
    )
    assert forged.status_code == 422
    listed = fixture.client.get("/projects?user_id=" + fixture.user_b.id, headers=fixture.headers_a)
    assert [item["id"] for item in listed.json()] == [created.json()["id"]]
    assert fixture.client.get("/projects", headers=fixture.headers_b).json() == []


def test_only_credential_digest_is_persisted(control_plane):
    fixture = control_plane
    with Session(fixture.engine) as session:
        stored = session.get(ApiCredential, fixture.credential_a.id)
        assert stored is not None
        valid_digest = (
            stored.token_hash == sha256(fixture.token_a.encode()).hexdigest()
            and len(stored.token_hash) == 64
            and stored.token_hash != fixture.token_a
        )
        assert valid_digest, "Credential storage must contain only its SHA256 digest"
    response = fixture.client.get("/projects", headers=fixture.headers_a)
    assert response.status_code == 200
    assert all(value not in response.text for value in (fixture.token_a,)), (
        "API response exposed an issued credential"
    )


@pytest.mark.parametrize("state", ["expired", "revoked", "inactive-user"])
def test_invalidated_credential_cannot_authenticate(control_plane, state):
    fixture = control_plane
    with Session(fixture.engine) as session:
        credential = session.get(ApiCredential, fixture.credential_a.id)
        if state == "expired":
            credential.created_at = datetime.now(UTC) - timedelta(days=2)
            credential.expires_at = datetime.now(UTC) - timedelta(days=1)
        elif state == "revoked":
            credential.revoked_at = datetime.now(UTC)
        else:
            session.get(User, fixture.user_a.id).is_active = False
        session.commit()
    response = fixture.client.get("/projects", headers=fixture.headers_a)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Authentication required"


def test_revoke_is_idempotent_and_invalidates_immediately(control_plane):
    fixture = control_plane
    with Session(fixture.engine) as session:
        assert revoke_credential(session, fixture.credential_a.id) is True
        first_revocation = session.get(ApiCredential, fixture.credential_a.id).revoked_at
        assert revoke_credential(session, fixture.credential_a.id) is True
        assert session.get(ApiCredential, fixture.credential_a.id).revoked_at == first_revocation
    assert fixture.client.get("/projects", headers=fixture.headers_a).status_code == 401
    assert fixture.client.get("/projects", headers=fixture.headers_b).status_code == 200


def test_disabled_quarantine_identity_cannot_receive_credentials(control_plane):
    with Session(control_plane.engine) as session:
        legacy = session.get(User, LEGACY_OWNER_ID)
        assert legacy is not None and legacy.is_active is False
        with pytest.raises(ValueError, match="inactive identity"):
            issue_credential(session, legacy.name)
        session.rollback()


def test_other_user_cannot_access_project(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    path = f"/projects/{project['id']}"
    for method, kwargs in (("get", {}), ("patch", {"json": {"name": "stolen"}}), ("delete", {})):
        response = getattr(fixture.client, method)(path, headers=fixture.headers_b, **kwargs)
        assert response.status_code == 404
    assert fixture.client.get(path, headers=fixture.headers_a).json() == project
    assert fixture.client.get("/projects", headers=fixture.headers_b).json() == []


def test_other_user_cannot_modify_service(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"])
    path = f"/projects/{project['id']}/services/{service['id']}"
    for method, kwargs in (
        ("get", {}),
        ("patch", {"json": {"resources": {"cpu": 16.0, "memory_mb": 65536}}}),
        ("delete", {}),
    ):
        response = getattr(fixture.client, method)(path, headers=fixture.headers_b, **kwargs)
        assert response.status_code == 404
    unauthorized_create = fixture.client.post(
        f"/projects/{project['id']}/services",
        headers=fixture.headers_b,
        json={"name": "intruder", "service_type": "worker"},
    )
    assert unauthorized_create.status_code == 404
    assert fixture.client.get(path, headers=fixture.headers_a).json() == service
    with Session(fixture.engine) as session:
        stored = session.get(Service, service["id"])
        assert stored.resources == {"cpu": 1.0, "memory_mb": 512}
        assert stored.desired_state == "stopped"


def test_service_id_cannot_cross_project_boundary(control_plane):
    fixture = control_plane
    first = create_project(fixture, "first-parent")
    second = create_project(fixture, "second-parent")
    service = create_service(fixture, first["id"])
    wrong_parent = f"/projects/{second['id']}/services/{service['id']}"
    for method, kwargs in (
        ("get", {}),
        ("patch", {"json": {"name": "reparented"}}),
        ("delete", {}),
    ):
        assert (
            getattr(fixture.client, method)(
                wrong_parent, headers=fixture.headers_a, **kwargs
            ).status_code
            == 404
        )
    with Session(fixture.engine) as session:
        assert session.get(Service, service["id"]).project_id == first["id"]


def test_unauthorized_errors_do_not_enumerate_resources(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"])
    existing_project = fixture.client.get(f"/projects/{project['id']}", headers=fixture.headers_b)
    absent_project = fixture.client.get(f"/projects/{uuid4()}", headers=fixture.headers_b)
    assert existing_project.status_code == absent_project.status_code == 404
    assert existing_project.json() == absent_project.json()
    existing_service = fixture.client.get(
        f"/projects/{project['id']}/services/{service['id']}",
        headers=fixture.headers_b,
    )
    absent_service = fixture.client.get(
        f"/projects/{uuid4()}/services/{uuid4()}",
        headers=fixture.headers_b,
    )
    assert existing_service.status_code == absent_service.status_code == 404
    assert existing_service.json() == absent_service.json()


def test_service_cannot_be_reparented_or_resurrected_by_payload(control_plane):
    fixture = control_plane
    first = create_project(fixture, "first")
    second = create_project(fixture, "second")
    service = create_service(fixture, first["id"])
    path = f"/projects/{first['id']}/services/{service['id']}"
    injected_parent = fixture.client.patch(
        path, headers=fixture.headers_a, json={"project_id": second["id"]}
    )
    assert injected_parent.status_code == 422
    archived = fixture.client.delete(path, headers=fixture.headers_a)
    assert archived.status_code == 200
    assert (
        fixture.client.patch(
            path, headers=fixture.headers_a, json={"desired_state": "running"}
        ).status_code
        == 409
    )
    with Session(fixture.engine) as session:
        stored = session.get(Service, service["id"])
        assert stored.project_id == first["id"]
        assert stored.desired_state == "archived"
        assert session.get(Project, first["id"]) is not None


def test_description_sql_text_is_metadata_not_executable(control_plane):
    fixture = control_plane
    description = "'; DROP TABLE users; --"
    response = fixture.client.post(
        "/projects",
        headers=fixture.headers_a,
        json={"name": "safe-sql-text", "description": description},
    )
    assert response.status_code == 201
    assert response.json()["description"] == description
    assert fixture.client.get("/projects", headers=fixture.headers_a).status_code == 200
    with Session(fixture.engine) as session:
        assert session.get(User, fixture.user_a.id) is not None
        assert session.get(User, fixture.user_b.id) is not None


def test_errors_and_logs_do_not_disclose_bearer_or_database_credentials(control_plane, caplog):
    fixture = control_plane
    database_canary = "postgresql+psycopg://canary:do-not-disclose@db/private"
    query_canary = "query-sensitive-canary"
    with caplog.at_level(logging.INFO):
        invalid = fixture.client.post(
            "/projects",
            headers=fixture.headers_a,
            json={"name": "invalid", "token": fixture.token_a, "database_url": database_canary},
        )
        unauthorized = fixture.client.get(
            "/projects?token=" + query_canary,
            headers={"Authorization": "Bearer invalid"},
        )
    assert invalid.status_code == 422
    assert unauthorized.status_code == 401
    application_logs = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("lava")
    )
    combined = json.dumps([invalid.json(), unauthorized.json()]) + application_logs
    assert all(
        value not in combined
        for value in (fixture.token_a, database_canary, "do-not-disclose", query_canary)
    ), "A credential canary appeared in the API response or application logs"
