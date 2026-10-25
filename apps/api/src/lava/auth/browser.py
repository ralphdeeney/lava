"""Database-backed browser sessions and explicit cookie CSRF protection."""

import re
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest

from fastapi import Request
from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from lava.auth.passwords import PASSWORD_HASHER, verify_password
from lava.core.settings import Settings
from lava.db.base import BrowserSession, LoginAttempt, PasswordAccount, User
from lava.domain.control_plane import ControlPlaneError

COOKIE_NAME = "lava_session"
SESSION_PATTERN = re.compile(r"lavabs_[A-Za-z0-9_-]{43}\Z")
LOGIN_LIMIT = 5
LOGIN_PEER_LIMIT = 50
LOGIN_WINDOW_SECONDS = 900


def token_hash(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def csrf_token(token: str) -> str:
    return sha256(("csrf:" + token).encode("ascii")).hexdigest()


def require_origin(request: Request, settings: Settings) -> None:
    if request.headers.get("origin") != settings.browser_origin:
        raise ControlPlaneError(403, "csrf", "Request origin is not allowed")


def require_csrf(request: Request, settings: Settings, raw_token: str) -> None:
    require_origin(request, settings)
    received = request.headers.get("x-csrf-token", "")
    if not received.isascii() or not compare_digest(received, csrf_token(raw_token)):
        raise ControlPlaneError(403, "csrf", "Request verification failed")


def authenticated_browser_session(
    session: Session, raw_token: str | None
) -> tuple[User, BrowserSession]:
    if raw_token is None or not SESSION_PATTERN.fullmatch(raw_token):
        raise ControlPlaneError(401, "unauthorized", "Authentication required")
    row = session.execute(
        select(User, BrowserSession)
        .join(BrowserSession, BrowserSession.user_id == User.id)
        .where(
            User.is_active.is_(True),
            BrowserSession.token_hash == token_hash(raw_token),
            BrowserSession.revoked_at.is_(None),
            BrowserSession.expires_at > datetime.now(UTC),
        )
    ).first()
    if row is None:
        raise ControlPlaneError(401, "unauthorized", "Authentication required")
    return row[0], row[1]


def consume_login_attempt(session: Session, username: str, peer: str) -> None:
    now = datetime.now(UTC)
    keys = (
        (
            sha256(("account:" + username.casefold() + "\x00" + peer).encode("utf-8")).hexdigest(),
            LOGIN_LIMIT,
        ),
        (sha256(("peer:" + peer).encode("utf-8")).hexdigest(), LOGIN_PEER_LIMIT),
    )
    # Each request cleans at most 100 stale buckets; no unbounded sweep in the API.
    stale = (
        select(LoginAttempt.bucket_hash)
        .where(LoginAttempt.window_started_at < now - timedelta(days=1))
        .limit(100)
    )
    session.execute(delete(LoginAttempt).where(LoginAttempt.bucket_hash.in_(stale)))
    expired = LoginAttempt.window_started_at <= now - timedelta(seconds=LOGIN_WINDOW_SECONDS)
    blocked = False
    for key, limit in keys:
        statement = insert(LoginAttempt).values(bucket_hash=key, window_started_at=now, attempts=1)
        statement = statement.on_conflict_do_update(
            index_elements=[LoginAttempt.bucket_hash],
            set_={
                "window_started_at": case((expired, now), else_=LoginAttempt.window_started_at),
                "attempts": case(
                    (expired, 1),
                    (LoginAttempt.attempts <= limit, LoginAttempt.attempts + 1),
                    else_=LoginAttempt.attempts,
                ),
            },
        ).returning(LoginAttempt.attempts)
        attempts = session.execute(statement).scalar_one()
        blocked = blocked or attempts > limit
    if blocked:
        session.commit()
        raise ControlPlaneError(429, "rate_limited", "Too many login attempts; try later")


def login(
    session: Session,
    username: str,
    password: str,
    peer: str,
    settings: Settings,
    previous_token: str | None,
) -> tuple[User, BrowserSession, str]:
    consume_login_attempt(session, username, peer)
    row = session.execute(
        select(User, PasswordAccount)
        .join(PasswordAccount, PasswordAccount.user_id == User.id)
        .where(User.name == username)
        .with_for_update(of=PasswordAccount)
    ).first()
    account = row[1] if row is not None else None
    valid = verify_password(password, account.password_hash if account is not None else None)
    if not valid or row is None or not row[0].is_active:
        session.commit()  # Failed attempts survive transaction/request boundaries.
        raise ControlPlaneError(401, "unauthorized", "Authentication required")
    user = row[0]
    if PASSWORD_HASHER.check_needs_rehash(account.password_hash):
        account.password_hash = PASSWORD_HASHER.hash(password)
    raw_token = "lavabs_" + secrets.token_urlsafe(32)
    if previous_token is not None and SESSION_PATTERN.fullmatch(previous_token):
        session.execute(
            update(BrowserSession)
            .where(
                BrowserSession.token_hash == token_hash(previous_token),
                BrowserSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
    browser_session = BrowserSession(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds),
    )
    session.add(browser_session)
    session.commit()
    return user, browser_session, raw_token
