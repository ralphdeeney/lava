"""Independent control-plane API/DB checks against a disposable real PostgreSQL DB."""

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration
API_ROOT = Path(__file__).resolve().parents[1]


class ControlPlaneFixture(SimpleNamespace):
    def __repr__(self):
        return "<DisposableControlPlaneFixture>"


def require_disposable_database():
    if os.environ.get("LAVA_INTEGRATION") != "1":
        pytest.skip("set LAVA_INTEGRATION=1 with a disposable PostgreSQL database")
    database = make_url(os.environ["LAVA_DATABASE_URL"]).database or ""
    if os.environ.get("LAVA_TEST_DATABASE_RESET") != "1" or not database.endswith("_test"):
        pytest.fail("Control-plane tests require reset acknowledgement and a *_test database")


@pytest.fixture
def control_plane():
    require_disposable_database()
    from lava.auth.credentials import issue_credential
    from lava.db.base import ApiCredential, Project, Service, User
    from lava.main import app

    subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
    engine = create_engine(os.environ["LAVA_DATABASE_URL"])
    identities = []
    with Session(engine, expire_on_commit=False) as session:
        first = issue_credential(session, "qa-owner-" + uuid4().hex)
        identities.append(first[0].id)
        second = issue_credential(session, "qa-other-" + uuid4().hex)
        identities.append(second[0].id)
    try:
        with TestClient(app) as client:
            yield ControlPlaneFixture(
                engine=engine,
                client=client,
                user_a=first[0],
                credential_a=first[1],
                token_a=first[2],
                user_b=second[0],
                credential_b=second[1],
                token_b=second[2],
                headers_a={"Authorization": "Bearer " + first[2]},
                headers_b={"Authorization": "Bearer " + second[2]},
            )
    finally:
        # Only rows owned by this fixture are removed; never truncate shared/operator data.
        with engine.begin() as connection:
            projects = select(Project.id).where(Project.owner_id.in_(identities))
            connection.execute(delete(Service).where(Service.project_id.in_(projects)))
            connection.execute(delete(Project).where(Project.owner_id.in_(identities)))
            connection.execute(delete(ApiCredential).where(ApiCredential.user_id.in_(identities)))
            connection.execute(delete(User).where(User.id.in_(identities)))
        engine.dispose()


def create_project(fixture, name="example", **changes):
    response = fixture.client.post(
        "/projects",
        headers=fixture.headers_a,
        json={"name": name, "description": "Independent QA project", **changes},
    )
    assert response.status_code == 201
    return response.json()


def create_service(fixture, project_id, name="frontend", **changes):
    response = fixture.client.post(
        f"/projects/{project_id}/services",
        headers=fixture.headers_a,
        json={
            "name": name,
            "service_type": "web",
            "resources": {"cpu": 1.0, "memory_mb": 512},
            **changes,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_project_create_retrieve_update_and_owned_list(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    UUID(project["id"])
    assert project["owner_id"] == fixture.user_a.id
    assert project["lifecycle_status"] == "active"
    assert project["created_at"] and project["updated_at"]
    fetched = fixture.client.get(f"/projects/{project['id']}", headers=fixture.headers_a)
    assert fetched.status_code == 200
    assert fetched.json() == project
    updated = fixture.client.patch(
        f"/projects/{project['id']}",
        headers=fixture.headers_a,
        json={"name": "renamed", "description": "Updated metadata"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "renamed"
    assert updated.json()["description"] == "Updated metadata"
    listed = fixture.client.get("/projects", headers=fixture.headers_a)
    assert listed.status_code == 200
    assert [value["id"] for value in listed.json()] == [project["id"]]
    assert fixture.client.get("/projects", headers=fixture.headers_b).json() == []


def test_project_names_are_unique_per_owner_and_conflicts_rollback(control_plane):
    fixture = control_plane
    project = create_project(fixture, "same-name")
    duplicate = fixture.client.post(
        "/projects", headers=fixture.headers_a, json={"name": "same-name"}
    )
    assert duplicate.status_code == 409
    assert (
        fixture.client.get(f"/projects/{project['id']}", headers=fixture.headers_a).status_code
        == 200
    )
    other_owner = fixture.client.post(
        "/projects",
        headers=fixture.headers_b,
        json={"name": "same-name"},
    )
    assert other_owner.status_code == 201
    assert other_owner.json()["owner_id"] == fixture.user_b.id
    assert create_project(fixture, "after-conflict")["id"] != project["id"]


def test_project_update_conflict_preserves_existing_state(control_plane):
    fixture = control_plane
    first = create_project(fixture, "first")
    second = create_project(fixture, "second")
    response = fixture.client.patch(
        f"/projects/{second['id']}",
        headers=fixture.headers_a,
        json={"name": first["name"]},
    )
    assert response.status_code == 409
    fetched = fixture.client.get(f"/projects/{second['id']}", headers=fixture.headers_a)
    assert fetched.json()["name"] == "second"


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": " "},
        {"name": "x" * 101},
        {"name": "valid", "owner_id": "00000000-0000-0000-0000-000000000000"},
        {"name": "valid", "lifecycle_status": "active"},
    ],
)
def test_invalid_project_requests_are_rejected(control_plane, body):
    response = control_plane.client.post("/projects", headers=control_plane.headers_a, json=body)
    assert response.status_code == 422


def test_project_listing_is_bounded_and_validated(control_plane):
    fixture = control_plane
    for name in ("one", "two", "three"):
        create_project(fixture, name)
    response = fixture.client.get("/projects?limit=2&offset=0", headers=fixture.headers_a)
    assert response.status_code == 200
    assert len(response.json()) == 2
    for query in ("limit=0", "limit=101", "offset=-1"):
        assert (
            fixture.client.get("/projects?" + query, headers=fixture.headers_a).status_code == 422
        )


@pytest.mark.parametrize("service_type", ["web", "api", "worker", "database"])
def test_service_creation_categories_and_metadata(control_plane, service_type):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"], service_type=service_type)
    UUID(service["id"])
    assert service["project_id"] == project["id"]
    assert service["service_type"] == service_type
    assert service["desired_state"] == "stopped"
    assert service["resources"] == {"cpu": 1.0, "memory_mb": 512}
    assert service["created_at"] and service["updated_at"]


def test_service_crud_preserves_archived_metadata(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"])
    route = f"/projects/{project['id']}/services/{service['id']}"
    fetched = fixture.client.get(route, headers=fixture.headers_a)
    assert fetched.status_code == 200
    assert fetched.json() == service
    listing = fixture.client.get(f"/projects/{project['id']}/services", headers=fixture.headers_a)
    assert [value["id"] for value in listing.json()] == [service["id"]]
    updated = fixture.client.patch(
        route,
        headers=fixture.headers_a,
        json={
            "name": "backend",
            "service_type": "api",
            "resources": {"cpu": 2.0, "memory_mb": 1024},
            "desired_state": "running",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "backend"
    assert updated.json()["resources"] == {"cpu": 2.0, "memory_mb": 1024}
    assert updated.json()["desired_state"] == "running"
    archived = fixture.client.delete(route, headers=fixture.headers_a)
    assert archived.status_code == 200
    assert archived.json()["desired_state"] == "archived"
    assert fixture.client.delete(route, headers=fixture.headers_a).json() == archived.json()
    assert (
        fixture.client.get(route, headers=fixture.headers_a).json()["desired_state"] == "archived"
    )
    assert (
        fixture.client.patch(
            route, headers=fixture.headers_a, json={"desired_state": "running"}
        ).status_code
        == 409
    )
    from lava.db.base import Service

    with Session(fixture.engine) as session:
        assert session.get(Service, service["id"]) is not None


def test_service_duplicates_are_project_scoped_and_rollback(control_plane):
    fixture = control_plane
    first_project = create_project(fixture, "first")
    second_project = create_project(fixture, "second")
    original = create_service(fixture, first_project["id"])
    duplicate = fixture.client.post(
        f"/projects/{first_project['id']}/services",
        headers=fixture.headers_a,
        json={"name": original["name"], "service_type": "web"},
    )
    assert duplicate.status_code == 409
    assert create_service(fixture, second_project["id"])["id"] != original["id"]
    assert (
        create_service(fixture, first_project["id"], name="after-conflict")["id"] != original["id"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"service_type": "shell"},
        {"resources": {"cpu": 0, "memory_mb": 512}},
        {"resources": {"cpu": 17, "memory_mb": 512}},
        {"resources": {"cpu": 1, "memory_mb": 63}},
        {"resources": {"cpu": 1, "memory_mb": 65537}},
        {"resources": {"cpu": 1, "memory_mb": "512"}},
        {"resources": {"cpu": 1, "memory_mb": 512, "privileged": True}},
        {"desired_state": "archived"},
        {"docker_socket": "/var/run/docker.sock"},
    ],
)
def test_invalid_service_configuration_is_rejected(control_plane, changes):
    fixture = control_plane
    project = create_project(fixture)
    response = fixture.client.post(
        f"/projects/{project['id']}/services",
        headers=fixture.headers_a,
        json={"name": "bad-config", "service_type": "web", **changes},
    )
    assert response.status_code == 422
    assert (
        fixture.client.get(f"/projects/{project['id']}/services", headers=fixture.headers_a).json()
        == []
    )


def test_archiving_project_preserves_rows_and_blocks_further_mutations(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"])
    project_route = f"/projects/{project['id']}"
    service_route = project_route + f"/services/{service['id']}"
    archived = fixture.client.delete(project_route, headers=fixture.headers_a)
    assert archived.status_code == 200
    assert archived.json()["lifecycle_status"] == "archived"
    assert fixture.client.delete(project_route, headers=fixture.headers_a).json() == archived.json()
    assert (
        fixture.client.get(service_route, headers=fixture.headers_a).json()["desired_state"]
        == "archived"
    )
    assert (
        fixture.client.patch(
            project_route, headers=fixture.headers_a, json={"name": "changed"}
        ).status_code
        == 409
    )
    assert (
        fixture.client.patch(
            service_route, headers=fixture.headers_a, json={"name": "changed"}
        ).status_code
        == 409
    )
    assert (
        fixture.client.post(
            project_route + "/services",
            headers=fixture.headers_a,
            json={"name": "new", "service_type": "web"},
        ).status_code
        == 409
    )
    from lava.db.base import Project, Service

    with Session(fixture.engine) as session:
        assert session.get(Project, project["id"]) is not None
        assert session.get(Service, service["id"]) is not None


def test_database_ownership_and_foreign_keys_are_enforced(control_plane):
    from lava.db.base import Project, Service

    fixture = control_plane
    with Session(fixture.engine) as session:
        session.add(Project(id=str(uuid4()), name="orphan-project", owner_id=str(uuid4())))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        project = create_project(fixture)
        session.add(
            Service(
                id=str(uuid4()),
                project_id=str(uuid4()),
                name="orphan-service",
                service_type="web",
                desired_state="stopped",
                resources={"cpu": 1.0, "memory_mb": 512},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.get(Project, project["id"]) is not None


def test_database_scoped_name_uniqueness_is_enforced(control_plane):
    from lava.db.base import Project, Service

    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"])
    with Session(fixture.engine) as session:
        session.add(Project(id=str(uuid4()), name=project["name"], owner_id=fixture.user_a.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(
            Service(
                id=str(uuid4()),
                project_id=project["id"],
                name=service["name"],
                service_type="web",
                desired_state="stopped",
                resources={"cpu": 1.0, "memory_mb": 512},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.get(Service, service["id"]) is not None


@contextmanager
def running_api_process():
    with socket.socket() as inherited:
        inherited.bind(("127.0.0.1", 0))
        inherited.listen()
        port = inherited.getsockname()[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "lava.main:app",
                "--fd",
                str(inherited.fileno()),
                "--no-access-log",
            ],
            cwd=API_ROOT,
            pass_fds=(inherited.fileno(),),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if process.poll() is not None:
                    pytest.fail("Disposable API process exited during startup")
                try:
                    with urlopen(base + "/health", timeout=0.2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.05)
            else:
                pytest.fail("Disposable API process failed its startup deadline")
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def request_json(base, path, token, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(
        base + path,
        data=data,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=5) as response:
        return response.status, json.load(response)


def test_project_and_service_survive_real_api_process_restart(control_plane):
    fixture = control_plane
    with running_api_process() as first:
        status, project = request_json(
            first, "/projects", fixture.token_a, {"name": "restart-project"}
        )
        assert status == 201
        status, service = request_json(
            first,
            f"/projects/{project['id']}/services",
            fixture.token_a,
            {"name": "restart-service", "service_type": "worker"},
        )
        assert status == 201
    with running_api_process() as second:
        assert request_json(second, f"/projects/{project['id']}", fixture.token_a) == (200, project)
        assert request_json(
            second, f"/projects/{project['id']}/services/{service['id']}", fixture.token_a
        ) == (200, service)


def test_partial_resources_update_does_not_discard_existing_configuration(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"], resources={"cpu": 1.0, "memory_mb": 1024})
    route = f"/projects/{project['id']}/services/{service['id']}"
    response = fixture.client.patch(
        route, headers=fixture.headers_a, json={"resources": {"cpu": 2.0}}
    )
    assert response.status_code in (200, 422)
    current = fixture.client.get(route, headers=fixture.headers_a).json()
    if response.status_code == 200:
        assert current["resources"] == {"cpu": 2.0, "memory_mb": 1024}
    else:
        assert current["resources"] == service["resources"]


@pytest.mark.parametrize("kind", ["project", "service"])
def test_database_lifecycle_constraints_are_enforced(control_plane, kind):
    from lava.db.base import Project, Service

    fixture = control_plane
    project = create_project(fixture)
    with Session(fixture.engine) as session:
        if kind == "project":
            record = Project(
                name="invalid-lifecycle", owner_id=fixture.user_a.id, lifecycle_status="deleted"
            )
        else:
            record = Service(
                name="invalid-lifecycle",
                project_id=project["id"],
                service_type="web",
                desired_state="deleted",
                resources={"cpu": 1.0, "memory_mb": 512},
            )
        session.add(record)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.get(Project, project["id"]) is not None


def test_control_plane_migration_refuses_unsafe_downgrade(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"])
    result = subprocess.run(
        ["alembic", "downgrade", "0001"], cwd=API_ROOT, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "Downgrade refused" in result.stdout + result.stderr
    assert (
        fixture.client.get(f"/projects/{project['id']}", headers=fixture.headers_a).status_code
        == 200
    )
    assert (
        fixture.client.get(
            f"/projects/{project['id']}/services/{service['id']}", headers=fixture.headers_a
        ).status_code
        == 200
    )


def test_empty_resources_update_is_a_metadata_noop(control_plane):
    fixture = control_plane
    project = create_project(fixture)
    service = create_service(fixture, project["id"], resources={"cpu": 3.0, "memory_mb": 2048})
    route = f"/projects/{project['id']}/services/{service['id']}"
    response = fixture.client.patch(route, headers=fixture.headers_a, json={"resources": {}})
    assert response.status_code == 200
    assert response.json()["resources"] == service["resources"]
    assert (
        fixture.client.get(route, headers=fixture.headers_a).json()["resources"]
        == service["resources"]
    )


def test_openapi_error_models_match_actual_unauthorized_and_validation_envelopes(control_plane):
    fixture = control_plane
    contract = fixture.client.get("/openapi.json").json()

    def resolve(schema):
        while "$ref" in schema:
            prefix = "#/components/schemas/"
            assert schema["$ref"].startswith(prefix)
            schema = contract["components"]["schemas"][schema["$ref"][len(prefix) :]]
        return schema

    unauthorized = fixture.client.get("/projects")
    invalid = fixture.client.post("/projects", headers=fixture.headers_a, json={"name": ""})
    assert unauthorized.status_code == 401
    assert invalid.status_code == 422
    for operation, status, response in (("get", "401", unauthorized), ("post", "422", invalid)):
        declared = contract["paths"]["/projects"][operation]["responses"][status]
        schema = resolve(declared["content"]["application/json"]["schema"])
        assert schema["type"] == "object"
        assert "error" in schema["required"]
        assert set(response.json()) == set(schema["properties"]) == {"error"}
        detail = resolve(schema["properties"]["error"])
        assert {"code", "message"}.issubset(detail["required"])
        assert set(response.json()["error"]) == {"code", "message"}
        assert detail["properties"]["code"]["type"] == "string"
        assert detail["properties"]["message"]["type"] == "string"
