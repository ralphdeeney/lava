import os
import subprocess
from pathlib import Path
from uuid import uuid4

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
        owner_id, project_id = str(uuid4()), str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users (id, name, is_active) VALUES (:id, :name, false)"),
                {"id": owner_id, "name": "migration-owner-" + uuid4().hex},
            )
            connection.execute(
                text("INSERT INTO projects (id, name, owner_id) VALUES (:id, 'test', :owner)"),
                {"id": project_id, "owner": owner_id},
            )
        try:
            with engine.connect() as connection:
                assert connection.execute(
                    text("SELECT owner_id FROM projects WHERE id = :id"), {"id": project_id}
                ).scalar_one() == owner_id
        finally:
            # Remove only this write probe before exercising a deliberately safe downgrade.
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
                connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": owner_id})
        subprocess.run(["alembic", "downgrade", "base"], check=True)
        assert "projects" not in inspect(engine).get_table_names()
        assert check_database(Settings()) is False
        subprocess.run(["alembic", "upgrade", "head"], check=True)
        subprocess.run(["alembic", "check"], check=True)
    finally:
        engine.dispose()


@pytest.mark.parametrize("name,acknowledgement", [("lava_test", "0"), ("production", "1")])
def test_destructive_suite_refuses_unsafe_target(monkeypatch, name, acknowledgement):
    monkeypatch.setenv("LAVA_INTEGRATION", "1")
    monkeypatch.setenv("LAVA_TEST_DATABASE_RESET", acknowledgement)
    monkeypatch.setenv("LAVA_DATABASE_URL", f"postgresql+psycopg://test:test@localhost/{name}")

    def forbidden(*args, **kwargs):
        raise AssertionError("No migration command may run before the safety guard")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(pytest.fail.Exception, match="Destructive tests require"):
        test_migration_round_trip()



@pytest.mark.integration
def test_legacy_project_is_preserved_by_owner_migration():
    if os.environ.get("LAVA_INTEGRATION") != "1":
        pytest.skip("set LAVA_INTEGRATION=1 with a disposable PostgreSQL database")
    database = make_url(os.environ["LAVA_DATABASE_URL"]).database or ""
    if os.environ.get("LAVA_TEST_DATABASE_RESET") != "1" or not database.endswith("_test"):
        pytest.fail("Destructive tests require LAVA_TEST_DATABASE_RESET=1 and a *_test database")
    from lava.db.base import LEGACY_OWNER_ID
    api_root = Path(__file__).resolve().parents[1]
    subprocess.run(["alembic", "upgrade", "head"], cwd=api_root, check=True)
    subprocess.run(["alembic", "downgrade", "0001"], cwd=api_root, check=True)
    engine = create_engine(os.environ["LAVA_DATABASE_URL"])
    project_id = str(uuid4())
    name = "legacy-" + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO projects (id, name) VALUES (:id, :name)"),
                               {"id": project_id, "name": name})
            created_at = connection.execute(text("SELECT created_at FROM projects WHERE id = :id"),
                                           {"id": project_id}).scalar_one()
        subprocess.run(["alembic", "upgrade", "head"], cwd=api_root, check=True)
        subprocess.run(["alembic", "upgrade", "head"], cwd=api_root, check=True)
        with engine.connect() as connection:
            project = connection.execute(
                text("SELECT name, owner_id, created_at FROM projects WHERE id = :id"),
                {"id": project_id},
            ).one()
            assert project.name == name
            assert project.owner_id == LEGACY_OWNER_ID
            assert project.created_at == created_at
            assert connection.execute(text("SELECT is_active FROM users WHERE id = :id"),
                                      {"id": LEGACY_OWNER_ID}).scalar_one() is False
            assert connection.execute(text("SELECT count(*) FROM api_credentials WHERE user_id = :id"),
                                      {"id": LEGACY_OWNER_ID}).scalar_one() == 0
        assert check_database(Settings()) is True
        subprocess.run(["alembic", "check"], cwd=api_root, check=True)
        subprocess.run(["alembic", "downgrade", "0001"], cwd=api_root, check=True)
        with engine.connect() as connection:
            restored = connection.execute(
                text("SELECT name, created_at FROM projects WHERE id = :id"), {"id": project_id}
            ).one()
            assert (restored.name, restored.created_at) == (name, created_at)
        assert check_database(Settings()) is False
        subprocess.run(["alembic", "upgrade", "head"], cwd=api_root, check=True)
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
        engine.dispose()



@pytest.mark.integration
@pytest.mark.parametrize("field,value", [("description", "Metadata must survive"),
                                          ("lifecycle_status", "archived")])
def test_edited_legacy_metadata_blocks_lossy_downgrade(field, value):
    if os.environ.get("LAVA_INTEGRATION") != "1":
        pytest.skip("set LAVA_INTEGRATION=1 with a disposable PostgreSQL database")
    database = make_url(os.environ["LAVA_DATABASE_URL"]).database or ""
    if os.environ.get("LAVA_TEST_DATABASE_RESET") != "1" or not database.endswith("_test"):
        pytest.fail("Destructive tests require LAVA_TEST_DATABASE_RESET=1 and a *_test database")
    api_root = Path(__file__).resolve().parents[1]
    subprocess.run(["alembic", "upgrade", "head"], cwd=api_root, check=True)
    subprocess.run(["alembic", "downgrade", "0001"], cwd=api_root, check=True)
    engine = create_engine(os.environ["LAVA_DATABASE_URL"])
    project_id = str(uuid4())
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO projects (id, name) VALUES (:id, :name)"),
                               {"id": project_id, "name": "edited-legacy-" + uuid4().hex})
        subprocess.run(["alembic", "upgrade", "head"], cwd=api_root, check=True)
        statements = {
            "description": text("UPDATE projects SET description = :value WHERE id = :id"),
            "lifecycle_status": text("UPDATE projects SET lifecycle_status = :value WHERE id = :id"),
        }
        with engine.begin() as connection:
            connection.execute(statements[field], {"value": value, "id": project_id})
        result = subprocess.run(["alembic", "downgrade", "0001"], cwd=api_root,
                                capture_output=True, text=True)
        assert result.returncode != 0
        assert "Downgrade refused" in result.stdout + result.stderr
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0002"
    finally:
        # Delete only this test's legacy row, even when the current buggy guard downgraded it.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
        if "users" not in inspect(engine).get_table_names():
            subprocess.run(["alembic", "upgrade", "head"], cwd=api_root, check=True)
        engine.dispose()
