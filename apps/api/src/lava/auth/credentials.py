"""High-entropy, expiring API credentials; only digests are persisted."""

import re
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from lava.db.base import ApiCredential, User

TOKEN_PATTERN = re.compile(r"lava_[A-Za-z0-9_-]{43}\Z")
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,99}\Z")


def digest_token(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def issue_credential(
    session: Session, name: str, ttl_hours: int = 24
) -> tuple[User, ApiCredential, str]:
    """Local administrative operation, never exposed by HTTP."""
    name = name.strip()
    if not NAME_PATTERN.fullmatch(name) or not 1 <= ttl_hours <= 720:
        raise ValueError("Valid name and ttl-hours between 1 and 720 are required")
    user = session.scalar(select(User).where(User.name == name).with_for_update())
    if user is None:
        user = User(name=name, is_active=True)
        session.add(user)
        session.flush()
    if not user.is_active:
        raise ValueError("Cannot issue a credential for an inactive identity")
    token = "lava_" + secrets.token_urlsafe(32)
    credential = ApiCredential(
        user_id=user.id,
        token_hash=digest_token(token),
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    session.add(credential)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return user, credential, token


def revoke_credential(session: Session, credential_id: str) -> bool:
    credential = session.get(ApiCredential, credential_id)
    if credential is None:
        return False
    if credential.revoked_at is None:
        credential.revoked_at = datetime.now(UTC)
        session.commit()
    return True
