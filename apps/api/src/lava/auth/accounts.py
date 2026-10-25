"""Local administrative password provisioning/reset. No public registration endpoint."""

import argparse
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from lava.auth.credentials import NAME_PATTERN
from lava.auth.passwords import hash_password
from lava.core.settings import get_settings
from lava.db.base import BrowserSession, PasswordAccount, User
from lava.persistence.database import engine_for_url


def provision_account(session: Session, name: str, password: str) -> User:
    name = name.strip()
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("A valid account name is required")
    encoded = hash_password(password)
    try:
        user = session.scalar(select(User).where(User.name == name).with_for_update())
        if user is None:
            user = User(name=name, is_active=True)
            session.add(user)
            session.flush()
        if not user.is_active:
            raise ValueError("Cannot provision an inactive identity")
        account = session.get(PasswordAccount, user.id)
        if account is None:
            session.add(PasswordAccount(user_id=user.id, password_hash=encoded))
        else:
            account.password_hash = encoded
        session.execute(
            update(BrowserSession)
            .where(BrowserSession.user_id == user.id, BrowserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        session.commit()
        return user
    except Exception:
        session.rollback()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    provision = commands.add_parser("provision")
    provision.add_argument("name")
    provision.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    try:
        if args.password_stdin:
            password = sys.stdin.readline(1026).removesuffix("\n")
        else:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Confirm password: "):
                raise ValueError("Password confirmation differs")
        settings = get_settings()
        with Session(engine_for_url(settings.database_url.get_secret_value())) as session:
            provision_account(session, args.name, password)
        print("Password account provisioned; existing browser sessions revoked")
    except (ValueError, SQLAlchemyError, EOFError):
        print("Account provisioning failed; check configuration and password requirements")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
