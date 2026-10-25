"""Independent negative security checks against disposable real PostgreSQL."""

import secrets

import pytest
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import Session
from test_browser_auth import ORIGIN, login
from test_browser_auth import browser_auth as browser_auth

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "cookie", ["invalid", "lavabs_" + "a" * 42, "lavabs_" + "a" * 44, "lavabs_" + "a" * 42 + "!"]
)
def test_malformed_browser_cookie_fails_closed(browser_auth, cookie):
    browser_auth.client.cookies.set("lava_session", cookie)
    assert browser_auth.client.get("/auth/session").status_code == 401
    assert browser_auth.client.get("/projects").status_code == 401


def test_csrf_from_another_session_cannot_authorize_mutation(browser_auth):
    fixture = browser_auth
    first = login(fixture)
    fixture.client.cookies.clear()
    second = login(fixture, 1)
    assert first.json()["csrf_token"] != second.json()["csrf_token"]
    response = fixture.client.post(
        "/projects",
        headers={"Origin": ORIGIN, "X-CSRF-Token": first.json()["csrf_token"]},
        json={"name": "blocked"},
    )
    assert response.status_code == 403
    assert fixture.client.get("/projects").json() == []


def test_valid_api_bearer_takes_precedence_over_browser_cookie(browser_auth):
    from lava.auth.credentials import issue_credential

    fixture = browser_auth
    login(fixture)
    with Session(fixture.engine, expire_on_commit=False) as session:
        _, _, token = issue_credential(session, fixture.names[1])
    response = fixture.client.post(
        "/projects", headers={"Authorization": "Bearer " + token}, json={"name": "bearer-owned"}
    )
    assert response.status_code == 201
    assert response.json()["owner_id"] == fixture.users[1].id
    assert fixture.client.get("/projects").json() == []
    assert (
        fixture.client.get(
            "/auth/session", headers={"Authorization": "Bearer " + token}
        ).status_code
        == 401
    )


def test_account_without_password_and_wrong_password_have_same_error(browser_auth):
    from lava.db.base import PasswordAccount

    fixture = browser_auth
    wrong = fixture.client.post(
        "/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": fixture.names[0], "password": secrets.token_urlsafe(32)},
    )
    with fixture.engine.begin() as connection:
        connection.execute(
            delete(PasswordAccount).where(PasswordAccount.user_id == fixture.users[1].id)
        )
    absent = fixture.client.post(
        "/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": fixture.names[1], "password": fixture.password},
    )
    assert wrong.status_code == absent.status_code == 401
    assert wrong.json() == absent.json()
    assert not fixture.client.cookies


@pytest.mark.parametrize(
    "secure,origin", [(False, "https://lava.example"), (True, "http://localhost:3000")]
)
def test_production_browser_settings_reject_unsafe_configuration(browser_auth, secure, origin):
    from lava.core.settings import get_settings

    values = get_settings().model_dump()
    values.update(environment="production", cookie_secure=secure, browser_origin=origin)
    with pytest.raises(ValidationError):
        type(get_settings())(**values)


def test_secure_cookie_configuration_is_preserved(browser_auth, monkeypatch):
    from lava.core.settings import get_settings

    monkeypatch.setenv("LAVA_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    response = login(browser_auth)
    attributes = {
        part.strip().lower().split("=", 1)[0]
        for part in response.headers["set-cookie"].split(";")[1:]
    }
    assert {"secure", "httponly", "samesite", "path"} <= attributes
    assert "domain" not in attributes
