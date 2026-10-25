"""Independent browser authentication checks; only disposable PostgreSQL is touched."""

import secrets
import subprocess
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from http.cookies import SimpleCookie
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_control_plane import API_ROOT, require_disposable_database

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:3000"


class BrowserFixture(SimpleNamespace):
    def __repr__(self):
        return "<DisposableBrowserAuthFixture>"


@pytest.fixture
def browser_auth(monkeypatch):
    import os

    from lava.auth.accounts import provision_account
    from lava.core.settings import get_settings
    from lava.db.base import (
        ApiCredential,
        BrowserSession,
        Environment,
        LoginAttempt,
        PasswordAccount,
        Project,
        ProjectInvitation,
        ProjectMembership,
        Service,
        User,
    )
    from lava.main import app

    require_disposable_database()
    monkeypatch.setenv("LAVA_BROWSER_ORIGIN", ORIGIN)
    monkeypatch.setenv("LAVA_COOKIE_SECURE", "false")
    get_settings.cache_clear()
    subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
    engine = create_engine(os.environ["LAVA_DATABASE_URL"])
    password = secrets.token_urlsafe(32)
    names = ["browser-" + uuid4().hex for _ in range(2)]
    peer = "qa-peer-" + uuid4().hex
    with Session(engine, expire_on_commit=False) as session:
        users = [provision_account(session, name, password) for name in names]
    try:
        with TestClient(app, client=(peer, 50000)) as client:
            yield BrowserFixture(
                engine=engine, client=client, users=users, names=names, password=password
            )
    finally:
        ids = [user.id for user in users]
        # Hash keys match only fixture accounts and the TestClient's actual transport peer.
        keys = [
            sha256(("account:" + name.casefold() + "\x00" + peer).encode()).hexdigest()
            for name in names
        ]
        keys.append(sha256(("peer:" + peer).encode()).hexdigest())
        with engine.begin() as connection:
            projects = select(Project.id).where(Project.owner_id.in_(ids))
            connection.execute(delete(Service).where(Service.project_id.in_(projects)))
            connection.execute(
                delete(ProjectInvitation).where(ProjectInvitation.project_id.in_(projects))
            )
            connection.execute(
                delete(ProjectMembership).where(ProjectMembership.project_id.in_(projects))
            )
            connection.execute(delete(Environment).where(Environment.project_id.in_(projects)))
            connection.execute(delete(Project).where(Project.owner_id.in_(ids)))
            for model in (BrowserSession, PasswordAccount, ApiCredential):
                connection.execute(delete(model).where(model.user_id.in_(ids)))
            connection.execute(delete(LoginAttempt).where(LoginAttempt.bucket_hash.in_(keys)))
            connection.execute(delete(User).where(User.id.in_(ids)))
        engine.dispose()
        get_settings.cache_clear()


def login(fixture, index=0):
    response = fixture.client.post(
        "/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": fixture.names[index], "password": fixture.password},
    )
    assert response.status_code == 200
    return response


def mutation_headers(response):
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def test_browser_login_and_session_are_authenticated(browser_auth):
    fixture = browser_auth
    response = login(fixture)
    assert response.json()["user"] == {"id": fixture.users[0].id, "name": fixture.names[0]}
    assert datetime.fromisoformat(response.json()["expires_at"]) > datetime.now(UTC)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    parsed_cookie = SimpleCookie()
    parsed_cookie.load(response.headers["set-cookie"])
    expires = parsed_cookie["lava_session"]["expires"]
    assert expires.endswith("GMT")
    assert parsedate_to_datetime(expires).utcoffset() == timedelta(0)
    session = fixture.client.get("/auth/session")
    assert session.status_code == 200
    assert session.json()["user"] == response.json()["user"]
    assert session.json()["csrf_token"] == response.json()["csrf_token"]
    assert fixture.client.get("/projects").status_code == 200


def test_browser_rejects_incorrect_credentials(browser_auth):
    fixture = browser_auth
    response = fixture.client.post(
        "/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": fixture.names[0], "password": secrets.token_urlsafe(32)},
    )
    assert response.status_code == 401
    assert fixture.client.get("/auth/session").status_code == 401
    assert not fixture.client.cookies


@pytest.mark.parametrize("origin", [None, "https://attacker.invalid", ORIGIN + ".attacker.invalid"])
def test_browser_login_requires_exact_origin(browser_auth, origin):
    headers = {} if origin is None else {"Origin": origin}
    response = browser_auth.client.post(
        "/auth/login",
        headers=headers,
        json={"username": browser_auth.names[0], "password": browser_auth.password},
    )
    assert response.status_code == 403
    assert not browser_auth.client.cookies


def test_browser_session_rotation_invalidates_previous_cookie(browser_auth):
    fixture = browser_auth
    login(fixture)
    previous = fixture.client.cookies.get("lava_session")
    login(fixture)
    assert fixture.client.cookies.get("lava_session") != previous
    fixture.client.cookies.clear()
    fixture.client.cookies.set("lava_session", previous)
    assert fixture.client.get("/auth/session").status_code == 401


@pytest.mark.parametrize("state", ["expired", "revoked", "inactive"])
def test_browser_session_expiry_revocation_and_disabled_user(browser_auth, state):
    from lava.db.base import BrowserSession, User

    fixture = browser_auth
    login(fixture)
    with fixture.engine.begin() as connection:
        if state == "inactive":
            connection.execute(
                update(User).where(User.id == fixture.users[0].id).values(is_active=False)
            )
        else:
            values = (
                {"revoked_at": datetime.now(UTC)}
                if state == "revoked"
                else {
                    "created_at": datetime.now(UTC) - timedelta(hours=2),
                    "expires_at": datetime.now(UTC) - timedelta(hours=1),
                }
            )
            connection.execute(
                update(BrowserSession)
                .where(BrowserSession.user_id == fixture.users[0].id)
                .values(**values)
            )
    assert fixture.client.get("/auth/session").status_code == 401
    assert fixture.client.get("/projects").status_code == 401


@pytest.mark.parametrize("mode", ["missing", "wrong_csrf", "wrong_origin", "forwarded_origin"])
def test_browser_mutations_require_origin_and_csrf(browser_auth, mode):
    fixture = browser_auth
    response = login(fixture)
    headers = mutation_headers(response)
    if mode == "missing":
        headers.pop("X-CSRF-Token")
    elif mode == "wrong_csrf":
        headers["X-CSRF-Token"] = "0" * 64
    else:
        headers["Origin"] = "https://attacker.invalid"
        if mode == "forwarded_origin":
            headers["X-Forwarded-Origin"] = ORIGIN
    assert (
        fixture.client.post("/projects", headers=headers, json={"name": "blocked"}).status_code
        == 403
    )
    assert fixture.client.get("/projects").json() == []
    assert fixture.client.post("/auth/logout", headers=headers).status_code == 403
    assert fixture.client.get("/auth/session").status_code == 200


@pytest.mark.parametrize("endpoint", ["/auth/logout", "/auth/logout-all"])
def test_browser_logout_invalidates_session(browser_auth, endpoint):
    fixture = browser_auth
    response = login(fixture)
    cookie = fixture.client.cookies.get("lava_session")
    logout = fixture.client.post(endpoint, headers=mutation_headers(response))
    assert logout.status_code == 200
    deletion = SimpleCookie()
    deletion.load(logout.headers["set-cookie"])
    morsel = deletion["lava_session"]
    assert morsel.value == "" and morsel["max-age"] == "0"
    assert morsel["path"] == "/" and morsel["httponly"] and morsel["samesite"] == "lax"
    assert parsedate_to_datetime(morsel["expires"]) <= datetime.now(UTC)
    assert fixture.client.get("/projects").status_code == 401
    fixture.client.cookies.set("lava_session", cookie)
    assert fixture.client.get("/auth/session").status_code == 401


@pytest.mark.parametrize("operation", ["logout-all", "password-reset"])
def test_browser_all_sessions_are_revoked(browser_auth, operation):
    from lava.auth.accounts import provision_account

    fixture = browser_auth
    login(fixture)
    first_cookie = fixture.client.cookies.get("lava_session")
    fixture.client.cookies.clear()  # Independent second login, not rotation.
    second = login(fixture)
    if operation == "logout-all":
        assert (
            fixture.client.post("/auth/logout-all", headers=mutation_headers(second)).status_code
            == 200
        )
    else:
        with Session(fixture.engine) as session:
            provision_account(session, fixture.names[0], secrets.token_urlsafe(32))
    for cookie in (first_cookie, fixture.client.cookies.get("lava_session")):
        fixture.client.cookies.clear()
        if cookie:
            fixture.client.cookies.set("lava_session", cookie)
        assert fixture.client.get("/auth/session").status_code == 401


def test_browser_cross_owner_access_is_hidden(browser_auth):
    fixture = browser_auth
    response = login(fixture)
    created = fixture.client.post(
        "/projects", headers=mutation_headers(response), json={"name": "private"}
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    service = fixture.client.post(
        f"/projects/{project_id}/services",
        headers=mutation_headers(response),
        json={"name": "private", "service_type": "web"},
    )
    assert service.status_code == 201
    fixture.client.cookies.clear()
    other = login(fixture, 1)
    assert fixture.client.get("/projects").json() == []
    assert fixture.client.get(f"/projects/{project_id}").status_code == 404
    assert (
        fixture.client.patch(
            f"/projects/{project_id}/services/{service.json()['id']}",
            headers=mutation_headers(other),
            json={"name": "stolen"},
        ).status_code
        == 404
    )


def test_browser_invalid_bearer_never_falls_back_to_cookie(browser_auth):
    fixture = browser_auth
    login(fixture)
    assert (
        fixture.client.get("/projects", headers={"Authorization": "Bearer invalid"}).status_code
        == 401
    )
    assert fixture.client.get("/projects").status_code == 200


def test_browser_login_rate_limit_survives_requests(browser_auth):
    fixture = browser_auth
    for _ in range(5):
        response = fixture.client.post(
            "/auth/login",
            headers={"Origin": ORIGIN},
            json={"username": fixture.names[0], "password": secrets.token_urlsafe(32)},
        )
        assert response.status_code == 401
    assert (
        fixture.client.post(
            "/auth/login",
            headers={"Origin": ORIGIN},
            json={"username": fixture.names[0], "password": fixture.password},
        ).status_code
        == 429
    )
    assert login(fixture, 1).status_code == 200


def test_browser_password_and_cookie_are_hashed_at_rest(browser_auth):
    from lava.db.base import BrowserSession, PasswordAccount

    fixture = browser_auth
    login(fixture)
    with Session(fixture.engine) as session:
        account = session.get(PasswordAccount, fixture.users[0].id)
        assert account.password_hash.startswith("$argon2id$")
        assert fixture.password not in account.password_hash
        row = session.scalar(
            select(BrowserSession).where(BrowserSession.user_id == fixture.users[0].id)
        )
        assert (
            row.token_hash
            == sha256(fixture.client.cookies.get("lava_session").encode()).hexdigest()
        )
    indexes = inspect(fixture.engine).get_indexes("browser_sessions")
    assert any(index["column_names"] == ["expires_at"] for index in indexes)


def test_browser_session_constraints_are_enforced(browser_auth):
    from lava.db.base import BrowserSession

    fixture = browser_auth
    for owner, created, expires in [
        (str(uuid4()), datetime.now(UTC), datetime.now(UTC) + timedelta(hours=1)),
        (fixture.users[0].id, datetime.now(UTC), datetime.now(UTC) - timedelta(hours=1)),
    ]:
        with Session(fixture.engine) as session:
            session.add(
                BrowserSession(
                    user_id=owner,
                    token_hash=secrets.token_hex(32),
                    created_at=created,
                    expires_at=expires,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()


def test_browser_errors_never_echo_credentials(browser_auth, caplog):
    fixture = browser_auth
    response = fixture.client.post(
        "/auth/login",
        headers={"Origin": ORIGIN},
        json={
            "username": fixture.names[0],
            "password": fixture.password,
            "unexpected": fixture.password,
        },
    )
    assert response.status_code == 422
    assert fixture.password not in response.text
    assert fixture.password not in caplog.text


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_https_browser_origin_never_allows_insecure_cookie(browser_auth, environment):
    from pydantic import ValidationError

    from lava.core.settings import Settings, get_settings

    values = get_settings().model_dump()
    values.update(
        environment=environment, browser_origin="https://lava.example", cookie_secure=False
    )
    with pytest.raises(ValidationError):
        Settings(**values)
