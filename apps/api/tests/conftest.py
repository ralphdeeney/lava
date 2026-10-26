import os
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("LAVA_DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")


@pytest.fixture(scope="session", autouse=True)
def junit_source_provenance(record_testsuite_property):
    """Bind generated reports to actual checkout, without including configuration secrets."""
    root = Path(__file__).resolve().parents[3]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    record_testsuite_property("source_commit", sha)
    if os.environ.get("LAVA_INTEGRATION") == "1":
        record_testsuite_property("test_environment", "real-postgresql")
    else:
        record_testsuite_property("test_environment", "unit")


@pytest.fixture(scope="session")
def executor_database():
    """A disposable, restricted runtime role; migration credentials stay in tests."""
    if os.environ.get("LAVA_INTEGRATION") != "1":
        pytest.skip("requires disposable PostgreSQL")
    import secrets
    from uuid import uuid4

    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import make_url

    from lava.persistence.executor_role import provision

    url = make_url(os.environ["LAVA_DATABASE_URL"])
    if not url.database.endswith("_test"):
        pytest.fail("Executor role tests require a disposable *_test database")
    role = "lava_executor_test_" + uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    admin_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin_url) as connection:
        provision(connection, password, role)
    try:
        yield url.set(username=role, password=password).render_as_string(hide_password=False), role
    finally:
        with psycopg.connect(admin_url) as connection:
            owner = connection.execute("SELECT current_user").fetchone()[0]
            connection.execute(
                sql.SQL("GRANT {} TO {} WITH INHERIT TRUE").format(
                    sql.Identifier(role), sql.Identifier(owner)
                )
            )
            connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
