"""Real PostgreSQL acceptance for environment isolation and service metadata."""

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_control_plane import control_plane as control_plane
from test_control_plane import create_project

from lava.db.base import Service

pytestmark = pytest.mark.integration


def test_environment_project_isolation_and_unique_slug(control_plane):
    fixture = control_plane
    project_a = create_project(fixture, "environment-a")["id"]
    other = fixture.client.post(
        "/projects", headers=fixture.headers_b, json={"name": "environment-b"}
    )
    assert other.status_code == 201
    project_b = other.json()["id"]
    first = fixture.client.post(
        f"/projects/{project_a}/environments",
        headers=fixture.headers_a,
        json={"name": "Staging", "slug": "staging", "description": "Isolated metadata"},
    )
    assert first.status_code == 201
    assert first.json()["project_id"] == project_a
    assert (
        fixture.client.get(
            f"/projects/{project_a}/environments", headers=fixture.headers_b
        ).status_code
        == 404
    )
    assert (
        fixture.client.post(
            f"/projects/{project_a}/environments",
            headers=fixture.headers_b,
            json={"name": "Wrong tenant", "slug": "other"},
        ).status_code
        == 404
    )
    duplicate = fixture.client.post(
        f"/projects/{project_a}/environments",
        headers=fixture.headers_a,
        json={"name": "Other", "slug": "staging"},
    )
    assert duplicate.status_code == 409
    distinct = fixture.client.post(
        f"/projects/{project_b}/environments",
        headers=fixture.headers_b,
        json={"name": "Staging", "slug": "staging"},
    )
    assert distinct.status_code == 201
    assert (
        fixture.client.get(
            f"/projects/{project_b}/environments/{first.json()['id']}",
            headers=fixture.headers_b,
        ).status_code
        == 404
    )
    archived = fixture.client.delete(
        f"/projects/{project_a}/environments/{first.json()['id']}",
        headers=fixture.headers_a,
    )
    assert archived.status_code == 200
    assert archived.json()["lifecycle_status"] == "archived"
    assert (
        fixture.client.patch(
            f"/projects/{project_a}/environments/{first.json()['id']}",
            headers=fixture.headers_a,
            json={"name": "Unsafe edit"},
        ).status_code
        == 409
    )


def test_railpack_service_configuration_metadata(control_plane):
    fixture = control_plane
    project = create_project(fixture, "railpack-config")["id"]
    environment = fixture.client.post(
        f"/projects/{project}/environments",
        headers=fixture.headers_a,
        json={"name": "Development", "slug": "development"},
    )
    assert environment.status_code == 201
    environment_id = environment.json()["id"]
    created = fixture.client.post(
        f"/projects/{project}/services",
        headers=fixture.headers_a,
        json={
            "name": "web",
            "service_type": "web",
            "environment_id": environment_id,
            "build_method": "railpack",
            "start_command": "python -m app",
            "deployment_branch": "feature/safe-ref",
            "desired_replicas": 2,
        },
    )
    assert created.status_code == 201
    service = created.json()
    assert service["environment_id"] == environment_id
    assert service["build_method"] == "railpack"
    assert service["config_revision"] == 1
    assert service["desired_replicas"] == 2
    updated = fixture.client.patch(
        f"/projects/{project}/services/{service['id']}",
        headers=fixture.headers_a,
        json={"desired_replicas": 3},
    )
    assert updated.status_code == 200
    assert updated.json()["config_revision"] == 2
    assert updated.json()["desired_replicas"] == 3
    assert (
        fixture.client.get(
            f"/projects/{project}/services/{service['id']}", headers=fixture.headers_a
        ).json()["config_revision"]
        == 2
    )
    detached = fixture.client.patch(
        f"/projects/{project}/services/{service['id']}",
        headers=fixture.headers_a,
        json={"environment_id": None},
    )
    assert detached.status_code == 200
    assert detached.json()["environment_id"] is None
    assert detached.json()["config_revision"] == 3
    reassigned = fixture.client.patch(
        f"/projects/{project}/services/{service['id']}",
        headers=fixture.headers_a,
        json={"environment_id": environment_id},
    )
    assert reassigned.status_code == 200
    assert reassigned.json()["environment_id"] == environment_id
    assert (
        fixture.client.patch(
            f"/projects/{project}/services/{service['id']}",
            headers=fixture.headers_a,
            json={"deployment_branch": "bad..ref"},
        ).status_code
        == 422
    )
    other = fixture.client.post(
        "/projects", headers=fixture.headers_b, json={"name": "other-env-project"}
    )
    assert other.status_code == 201
    foreign = fixture.client.post(
        f"/projects/{other.json()['id']}/environments",
        headers=fixture.headers_b,
        json={"name": "Production", "slug": "production"},
    )
    assert foreign.status_code == 201
    with Session(fixture.engine) as session:
        with pytest.raises(IntegrityError), session.begin():
            session.execute(
                update(Service)
                .where(Service.id == service["id"])
                .values(environment_id=foreign.json()["id"])
            )
    assert (
        fixture.client.patch(
            f"/projects/{project}/services/{service['id']}",
            headers=fixture.headers_a,
            json={"environment_id": foreign.json()["id"]},
        ).status_code
        == 404
    )
    assert (
        fixture.client.delete(
            f"/projects/{project}/environments/{environment_id}", headers=fixture.headers_a
        ).status_code
        == 200
    )
    preserved = fixture.client.get(
        f"/projects/{project}/services/{service['id']}", headers=fixture.headers_a
    )
    assert preserved.status_code == 200
    assert preserved.json()["environment_id"] == environment_id
    assert (
        fixture.client.patch(
            f"/projects/{project}/services/{service['id']}",
            headers=fixture.headers_a,
            json={"desired_replicas": 4},
        ).status_code
        == 409
    )
