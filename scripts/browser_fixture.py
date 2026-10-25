"""Private disposable-browser fixture operations; never exposed as HTTP endpoints."""

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from lava.auth.browser import SESSION_PATTERN, token_hash
from lava.db.base import BrowserSession, LoginAttempt, User


def require_test_database() -> str:
    url = os.environ.get("LAVA_DATABASE_URL", "")
    parsed = make_url(url)
    if (
        os.environ.get("LAVA_INTEGRATION") != "1"
        or os.environ.get("LAVA_TEST_DATABASE_RESET") != "1"
        or parsed.drivername != "postgresql+psycopg"
        or not (parsed.database or "").endswith("_test")
    ):
        raise ValueError(
            "Only an explicitly acknowledged disposable PostgreSQL test DB is allowed"
        )
    return url


def main() -> int:
    engine = None
    try:
        url = require_test_database()
        private = Path(os.environ["LAVA_E2E_ACCOUNTS_FILE"])
        if private.stat().st_mode & 0o077:
            raise ValueError("Private fixture permissions must be0600")
        users = json.loads(private.read_text())["users"]
        payload = json.loads(sys.stdin.read(4096))
        engine = create_engine(url)
        with Session(engine) as session:
            for user in users:
                row = session.get(User, user["id"])
                if row is None or row.name != user["username"]:
                    raise ValueError("Fixture identity does not match")
            if payload.get("action") == "reset_login_attempts":
                # These are the owned accounts and loopback peer in this isolated harness.
                keys = [
                    sha256(
                        (
                            "account:" + u["username"].casefold() + "\x00127.0.0.1"
                        ).encode()
                    ).hexdigest()
                    for u in users
                ]
                keys.append(sha256(b"peer:127.0.0.1").hexdigest())
                session.execute(
                    delete(LoginAttempt).where(LoginAttempt.bucket_hash.in_(keys))
                )
            else:
                user_id, raw = payload["user_id"], payload["session_token"]
                if user_id not in {
                    u["id"] for u in users
                } or not SESSION_PATTERN.fullmatch(raw):
                    raise ValueError("Invalid fixture session")
                row = session.scalar(
                    select(BrowserSession).where(
                        BrowserSession.user_id == user_id,
                        BrowserSession.token_hash == token_hash(raw),
                    )
                )
                if row is None:
                    raise ValueError("Owned session not found")
                row.created_at = datetime.now(UTC) - timedelta(seconds=2)
                row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        return 0
    except Exception:
        # Never echo stdin, credentials, DB URLs or arbitrary exception diagnostics.
        print("Disposable browser fixture operation failed", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
