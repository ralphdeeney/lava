from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from lava.auth.browser import COOKIE_NAME, authenticated_browser_session, require_csrf
from lava.auth.credentials import TOKEN_PATTERN, digest_token
from lava.core.settings import Settings, get_settings
from lava.db.base import ApiCredential, User
from lava.domain.control_plane import ControlPlaneError
from lava.persistence.database import get_session

bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
    credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if "authorization" not in request.headers:
        raw_token = request.cookies.get(COOKIE_NAME)
        user, _ = authenticated_browser_session(session, raw_token)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_csrf(request, settings, raw_token)
        return user
    # An invalid Authorization header must never fall back to a valid cookie.
    if credential is None or not TOKEN_PATTERN.fullmatch(credential.credentials):
        raise ControlPlaneError(401, "unauthorized", "Authentication required")
    user = session.scalar(
        select(User)
        .join(ApiCredential, ApiCredential.user_id == User.id)
        .where(
            User.is_active.is_(True),
            ApiCredential.token_hash == digest_token(credential.credentials),
            ApiCredential.revoked_at.is_(None),
            ApiCredential.expires_at > datetime.now(UTC),
        )
    )
    if user is None:
        raise ControlPlaneError(401, "unauthorized", "Authentication required")
    return user
