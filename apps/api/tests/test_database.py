import os
import subprocess

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from lava.core.settings import Settings
from lava.main import check_database


@pytest.mark.integration
def test_migration_round_trip():
    if os.environ.get("LAVA_INTEGRATION") != "1":
        pytest.skip("set LAVA_INTEGRATION=1 with a disposable PostgreSQL database")
    database = make_url(os.environ["LAVA_DATABASE_URL"]).database or ""
    if os.environ.get("LAVA_TEST_DATABASE_RESET") != "1" or not database.endswith("_test"):
        pytest.fail("Destructive tests require LAVA_TEST_DATABASE_RESET=1 and a *_test database")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    engine = create_engine(os.environ["LAVA_DATABASE_URL"])
    try:
        assert "projects" in inspect(engine).get_table_names()
        assert check_database(Settings()) is True
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO projects (id, name) VALUES ('test', 'test')"))
        subprocess.run(["alembic", "downgrade", "base"], check=True)
        assert "projects" not in inspect(engine).get_table_names()
        assert check_database(Settings()) is False
        subprocess.run(["alembic", "upgrade", "head"], check=True)
        subprocess.run(["alembic", "check"], check=True)
    finally:
        engine.dispose()
