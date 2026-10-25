"""Browser authentication endpoints; session secrets never appear in response bodies."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import update
from sqlalchemy.orm import Session

from lava.api.schemas import ErrorResponse
from lava.auth.browser import (
    COOKIE_NAME,
    authenticated_browser_session,
    csrf_token,
    login,
    require_csrf,
    require_origin,
)
from lava.core.settings import Settings, get_settings
from lava.db.base import BrowserSession
from lava.domain.control_plane import ControlPlaneError
from lava.persistence.database import get_session

router = APIRouter(
    prefix="/auth",
    tags=["browser-auth"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 422, 429, 503)},
)
Database = Annotated[Session, Depends(get_session)]
Configuration = Annotated[Settings, Depends(get_settings)]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username is required")
        return value


class SessionUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str


class SessionView(BaseModel):
    user: SessionUser
    expires_at: datetime
    csrf_token: str


class LogoutView(BaseModel):
    status: str


def view(user, browser_session: BrowserSession, raw_token: str) -> SessionView:
    return SessionView(
        user=SessionUser.model_validate(user),
        expires_at=browser_session.expires_at,
        csrf_token=csrf_token(raw_token),
    )


def cookie_session(request: Request, session: Session):
    # These endpoints explicitly manage browser sessions, never API bearer credentials.
    if "authorization" in request.headers:
        raise ControlPlaneError(401, "unauthorized", "Authentication required")
    raw_token = request.cookies.get(COOKIE_NAME)
    user, browser_session = authenticated_browser_session(session, raw_token)
    return user, browser_session, raw_token


@router.post("/login", response_model=SessionView)
def login_browser(
    body: LoginInput,
    request: Request,
    response: Response,
    session: Database,
    settings: Configuration,
):
    require_origin(request, settings)
    peer = request.client.host if request.client is not None else "unknown"
    user, browser_session, raw_token = login(
        session,
        body.username,
        body.password.get_secret_value(),
        peer,
        settings,
        request.cookies.get(COOKIE_NAME),
    )
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        max_age=settings.session_ttl_seconds,
        expires=browser_session.expires_at,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return view(user, browser_session, raw_token)


@router.get("/session", response_model=SessionView)
def read_session(request: Request, session: Database):
    user, browser_session, raw_token = cookie_session(request, session)
    return view(user, browser_session, raw_token)


@router.post("/logout", response_model=LogoutView)
def logout_browser(
    request: Request,
    response: Response,
    session: Database,
    settings: Configuration,
):
    _, browser_session, raw_token = cookie_session(request, session)
    require_csrf(request, settings, raw_token)
    browser_session.revoked_at = datetime.now(UTC)
    session.commit()
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
    )
    return LogoutView(status="logged_out")


@router.post("/logout-all", response_model=LogoutView)
def logout_all_browser(
    request: Request,
    response: Response,
    session: Database,
    settings: Configuration,
):
    user, _, raw_token = cookie_session(request, session)
    require_csrf(request, settings, raw_token)
    session.execute(
        update(BrowserSession)
        .where(BrowserSession.user_id == user.id, BrowserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    session.commit()
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
    )
    return LogoutView(status="logged_out")
