"""Independent tenant-boundary attacks against disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_browser_auth import ORIGIN, login, mutation_headers
from test_browser_auth import browser_auth as browser_auth
from test_control_plane import control_plane as control_plane
from test_control_plane import create_project, create_service

from lava.db.base import Project, ProjectInvitation, ProjectMembership

pytestmark = pytest.mark.integration


def add_member(fixture, project_id: str, role: str) -> dict:
    response = fixture.client.post(
        f"/projects/{project_id}/members",
        headers=fixture.headers_a,
        json={"username": fixture.user_b.name, "role": role},
    )
    assert response.status_code == 201
    return response.json()


def owner_member(fixture, project_id: str) -> dict:
    response = fixture.client.get(f"/projects/{project_id}/members", headers=fixture.headers_a)
    assert response.status_code == 200
    return next(member for member in response.json() if member["user_id"] == fixture.user_a.id)


def test_cross_project_membership_and_environment_ids_do_not_grant_access(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"])
    prefix = f"/projects/{project['id']}"
    paths = (
        prefix,
        prefix + "/members",
        prefix + "/invitations",
        prefix + "/environments",
        prefix + f"/services/{service['id']}",
    )
    for path in paths:
        response = fixture.client.get(path, headers=fixture.headers_b)
        assert response.status_code == 404, path
        assert project["name"] not in response.text
    assert fixture.client.get("/projects", headers=fixture.headers_b).json() == []
    for path, body in (
        (prefix + "/members", {"username": fixture.user_b.name, "role": "admin"}),
        (prefix + "/environments", {"name": "staging", "slug": "staging"}),
        (prefix + f"/services/{service['id']}", {"name": "stolen"}),
    ):
        assert fixture.client.post(path, headers=fixture.headers_b, json=body).status_code in {
            404,
            405,
        }
    assert (
        fixture.client.patch(
            prefix + f"/services/{service['id']}",
            headers=fixture.headers_b,
            json={"name": "stolen"},
        ).status_code
        == 404
    )
    assert fixture.client.get(prefix, headers=fixture.headers_a).json()["id"] == project["id"]


def test_member_cannot_escalate_roles(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    prefix = f"/projects/{project['id']}"
    member = add_member(fixture, project["id"], "viewer")
    assert fixture.client.get(prefix, headers=fixture.headers_b).status_code == 200
    for path, body in (
        (prefix + "/services", {"name": "forbidden", "service_type": "web"}),
        (prefix + "/environments", {"name": "forbidden", "slug": "forbidden"}),
        (prefix + "/invitations", {"username": fixture.user_a.name, "role": "admin"}),
    ):
        assert fixture.client.post(path, headers=fixture.headers_b, json=body).status_code == 404
    assert (
        fixture.client.patch(
            prefix + f"/members/{member['id']}",
            headers=fixture.headers_b,
            json={"role": "admin"},
        ).status_code
        == 404
    )
    assert (
        fixture.client.patch(
            prefix,
            headers=fixture.headers_b,
            json={"name": "forbidden"},
        ).status_code
        == 404
    )

    assert (
        fixture.client.patch(
            prefix + f"/members/{member['id']}",
            headers=fixture.headers_a,
            json={"role": "developer"},
        ).status_code
        == 200
    )
    assert (
        fixture.client.post(
            prefix + "/environments",
            headers=fixture.headers_b,
            json={"name": "development", "slug": "development"},
        ).status_code
        == 201
    )
    assert (
        fixture.client.post(
            prefix + "/invitations",
            headers=fixture.headers_b,
            json={"username": fixture.user_a.name, "role": "viewer"},
        ).status_code
        == 404
    )

    assert (
        fixture.client.patch(
            prefix + f"/members/{member['id']}",
            headers=fixture.headers_a,
            json={"role": "admin"},
        ).status_code
        == 200
    )
    owner = owner_member(fixture, project["id"])
    assert (
        fixture.client.post(
            prefix + "/members",
            headers=fixture.headers_b,
            json={"username": fixture.user_a.name, "role": "owner"},
        ).status_code
        == 422
    )
    assert (
        fixture.client.patch(
            prefix + f"/members/{owner['id']}",
            headers=fixture.headers_b,
            json={"role": "viewer"},
        ).status_code
        == 409
    )
    assert fixture.client.get(prefix, headers=fixture.headers_a).json()["name"] == project["name"]


def test_final_owner_cannot_be_removed_or_demoted(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    owner = owner_member(fixture, project["id"])
    path = f"/projects/{project['id']}/members/{owner['id']}"
    assert fixture.client.delete(path, headers=fixture.headers_a).status_code == 409
    assert (
        fixture.client.patch(path, headers=fixture.headers_a, json={"role": "admin"}).status_code
        == 409
    )
    with Session(fixture.engine) as session:
        stored = session.get(ProjectMembership, owner["id"])
        assert stored is not None
        assert stored.role == "owner" and stored.status == "active"
    assert (
        fixture.client.get(f"/projects/{project['id']}", headers=fixture.headers_a).status_code
        == 200
    )


def test_revoked_member_immediately_denied(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"])
    member = add_member(fixture, project["id"], "developer")
    prefix = f"/projects/{project['id']}"
    assert fixture.client.get(prefix, headers=fixture.headers_b).status_code == 200
    assert (
        fixture.client.patch(
            prefix + f"/services/{service['id']}",
            headers=fixture.headers_b,
            json={"name": "developer-change"},
        ).status_code
        == 200
    )
    response = fixture.client.delete(prefix + f"/members/{member['id']}", headers=fixture.headers_a)
    assert response.status_code == 200 and response.json()["status"] == "revoked"
    for path in (prefix, prefix + "/members", prefix + f"/services/{service['id']}"):
        assert fixture.client.get(path, headers=fixture.headers_b).status_code == 404
    assert (
        fixture.client.patch(
            prefix + f"/services/{service['id']}",
            headers=fixture.headers_b,
            json={"name": "after-revocation"},
        ).status_code
        == 404
    )
    assert fixture.client.get("/projects", headers=fixture.headers_b).json() == []
    assert (
        fixture.client.get(prefix + f"/services/{service['id']}", headers=fixture.headers_a).json()[
            "name"
        ]
        == "developer-change"
    )


def test_concurrent_revoke_precedes_blocked_service_write(control_plane):
    fixture = control_plane
    project = create_project(fixture, "concurrent-revocation")
    service = create_service(fixture, project["id"])
    member = add_member(fixture, project["id"], "developer")
    started = Event()

    def write_service():
        started.set()
        return fixture.client.patch(
            f"/projects/{project['id']}/services/{service['id']}",
            headers=fixture.headers_b,
            json={"name": "must-not-persist"},
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(fixture.engine) as database:
            with database.begin():
                database.scalar(
                    select(Project).where(Project.id == project["id"]).with_for_update()
                )
                future = pool.submit(write_service)
                assert started.wait(timeout=5)
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.1)
                database.execute(
                    update(ProjectMembership)
                    .where(ProjectMembership.id == member["id"])
                    .values(status="revoked", revoked_at=datetime.now(UTC))
                )
        assert future.result(timeout=10).status_code == 404
    assert (
        fixture.client.get(
            f"/projects/{project['id']}/services/{service['id']}",
            headers=fixture.headers_a,
        ).json()["name"]
        == service["name"]
    )


def test_invitation_single_use_expiry_and_revocation(control_plane):
    fixture = control_plane
    project = create_project(fixture, "invite-once")
    prefix = f"/projects/{project['id']}"
    invitation = fixture.client.post(
        prefix + "/invitations",
        headers=fixture.headers_a,
        json={"username": fixture.user_b.name, "role": "viewer"},
    )
    assert invitation.status_code == 201
    invite_id = invitation.json()["id"]
    assert (
        fixture.client.post(
            prefix + "/invitations",
            headers=fixture.headers_a,
            json={"username": fixture.user_b.name, "role": "viewer"},
        ).status_code
        == 409
    )
    path = f"/invitations/{invite_id}/accept"
    assert fixture.client.post(path, headers=fixture.headers_a, json={}).status_code == 404
    assert fixture.client.post(path, headers=fixture.headers_b, json={}).status_code == 200
    assert fixture.client.post(path, headers=fixture.headers_b, json={}).status_code == 409
    assert fixture.client.get(prefix, headers=fixture.headers_b).status_code == 200

    expired_project = create_project(fixture, "invite-expired")
    expired = fixture.client.post(
        f"/projects/{expired_project['id']}/invitations",
        headers=fixture.headers_a,
        json={"username": fixture.user_b.name, "role": "developer"},
    )
    assert expired.status_code == 201
    with fixture.engine.begin() as connection:
        connection.execute(
            update(ProjectInvitation)
            .where(ProjectInvitation.id == expired.json()["id"])
            .values(
                created_at=datetime.now(UTC) - timedelta(days=2),
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
    assert (
        fixture.client.post(
            f"/invitations/{expired.json()['id']}/accept", headers=fixture.headers_b, json={}
        ).status_code
        == 410
    )
    with Session(fixture.engine) as session:
        assert session.get(ProjectInvitation, expired.json()["id"]).status == "expired"
    assert (
        fixture.client.get(
            f"/projects/{expired_project['id']}", headers=fixture.headers_b
        ).status_code
        == 404
    )

    revoked_project = create_project(fixture, "invite-revoked")
    revoked = fixture.client.post(
        f"/projects/{revoked_project['id']}/invitations",
        headers=fixture.headers_a,
        json={"username": fixture.user_b.name, "role": "admin"},
    )
    assert revoked.status_code == 201
    assert (
        fixture.client.delete(
            f"/projects/{revoked_project['id']}/invitations/{revoked.json()['id']}",
            headers=fixture.headers_a,
        ).status_code
        == 200
    )
    assert (
        fixture.client.post(
            f"/invitations/{revoked.json()['id']}/accept", headers=fixture.headers_b, json={}
        ).status_code
        == 409
    )
    assert (
        fixture.client.get(
            f"/projects/{revoked_project['id']}", headers=fixture.headers_b
        ).status_code
        == 404
    )

    archived_project = create_project(fixture, "invite-archived")
    archived_invite = fixture.client.post(
        f"/projects/{archived_project['id']}/invitations",
        headers=fixture.headers_a,
        json={"username": fixture.user_b.name, "role": "viewer"},
    )
    assert archived_invite.status_code == 201
    assert (
        fixture.client.delete(
            f"/projects/{archived_project['id']}", headers=fixture.headers_a
        ).status_code
        == 200
    )
    assert archived_invite.json()["id"] not in {
        invitation["id"]
        for invitation in fixture.client.get("/invitations", headers=fixture.headers_b).json()
    }
    assert fixture.client.post(
        f"/invitations/{archived_invite.json()['id']}/accept",
        headers=fixture.headers_b,
        json={},
    ).status_code in {404, 409}


def test_forged_owner_membership_cannot_enumerate_canonical_project(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    with Session(fixture.engine) as session:
        session.add(
            ProjectMembership(project_id=project["id"], user_id=fixture.user_b.id, role="owner")
        )
        session.commit()
    assert (
        fixture.client.get(f"/projects/{project['id']}", headers=fixture.headers_b).status_code
        == 404
    )
    assert fixture.client.get("/projects", headers=fixture.headers_b).json() == []


def test_membership_cookie_mutations_require_origin_and_csrf(browser_auth):
    fixture = browser_auth
    logged_in = login(fixture)
    project = fixture.client.post(
        "/projects",
        headers=mutation_headers(logged_in),
        json={"name": "cookie-security-" + uuid4().hex[:12]},
    )
    assert project.status_code == 201
    path = f"/projects/{project.json()['id']}/environments"
    payload = {"name": "staging", "slug": "staging"}
    assert fixture.client.post(path, json=payload).status_code == 403
    assert (
        fixture.client.post(
            path,
            headers={"Origin": ORIGIN, "X-CSRF-Token": "0" * 64},
            json=payload,
        ).status_code
        == 403
    )
    assert (
        fixture.client.post(path, headers=mutation_headers(logged_in), json=payload).status_code
        == 201
    )


def test_invalid_configuration_error_does_not_echo_submitted_value(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    marker = "bad-branch-" + uuid4().hex
    response = fixture.client.post(
        f"/projects/{project['id']}/services",
        headers=fixture.headers_a,
        json={
            "name": "secure-service",
            "service_type": "web",
            "deployment_branch": marker + " with spaces",
        },
    )
    assert response.status_code == 422
    assert marker not in response.text
    assert (
        fixture.client.get(f"/projects/{project['id']}/services", headers=fixture.headers_a).json()
        == []
    )
