import os
import secrets
import subprocess
from datetime import UTC, datetime, timedelta
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
                assert (
                    connection.execute(
                        text("SELECT owner_id FROM projects WHERE id = :id"), {"id": project_id}
                    ).scalar_one()
                    == owner_id
                )
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
            connection.execute(
                text("INSERT INTO projects (id, name) VALUES (:id, :name)"),
                {"id": project_id, "name": name},
            )
            created_at = connection.execute(
                text("SELECT created_at FROM projects WHERE id = :id"), {"id": project_id}
            ).scalar_one()
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
            assert (
                connection.execute(
                    text("SELECT is_active FROM users WHERE id = :id"), {"id": LEGACY_OWNER_ID}
                ).scalar_one()
                is False
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM api_credentials WHERE user_id = :id"),
                    {"id": LEGACY_OWNER_ID},
                ).scalar_one()
                == 0
            )
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
            if "project_memberships" in inspect(engine).get_table_names():
                connection.execute(
                    text("DELETE FROM project_memberships WHERE project_id = :id"),
                    {"id": project_id},
                )
            connection.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
        engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize(
    "field,value",
    [
        ("description", "Metadata must survive"),
        ("lifecycle_status", "archived"),
        ("updated_at", "increment"),
    ],
)
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
            connection.execute(
                text("INSERT INTO projects (id, name) VALUES (:id, :name)"),
                {"id": project_id, "name": "edited-legacy-" + uuid4().hex},
            )
        subprocess.run(["alembic", "upgrade", "head"], cwd=api_root, check=True)
        statements = {
            "description": text("UPDATE projects SET description = :value WHERE id = :id"),
            "lifecycle_status": text(
                "UPDATE projects SET lifecycle_status = :value WHERE id = :id"
            ),
            "updated_at": text(
                "UPDATE projects SET updated_at = updated_at + INTERVAL '1 second' WHERE id = :id"
            ),
        }
        with engine.begin() as connection:
            connection.execute(statements[field], {"value": value, "id": project_id})
        result = subprocess.run(
            ["alembic", "downgrade", "0001"], cwd=api_root, capture_output=True, text=True
        )
        assert result.returncode != 0
        assert "Downgrade refused" in result.stdout + result.stderr
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0006"
            )
    finally:
        # Delete only this test's legacy row, even when the current buggy guard downgraded it.
        with engine.begin() as connection:
            if "project_memberships" in inspect(engine).get_table_names():
                connection.execute(
                    text("DELETE FROM project_memberships WHERE project_id = :id"),
                    {"id": project_id},
                )
            connection.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
        if "users" not in inspect(engine).get_table_names():
            subprocess.run(["alembic", "upgrade", "head"], cwd=api_root, check=True)
        engine.dispose()


@pytest.mark.integration
def test_browser_migration_preserves_existing_owned_metadata():
    from test_control_plane import API_ROOT, require_disposable_database

    require_disposable_database()
    subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
    subprocess.run(["alembic", "downgrade", "0002"], cwd=API_ROOT, check=True)
    engine = create_engine(os.environ["LAVA_DATABASE_URL"])
    owner_id, project_id, service_id, credential_id = (str(uuid4()) for _ in range(4))
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users(id,name,is_active) VALUES (:id,:name,true)"),
                {"id": owner_id, "name": "existing-" + uuid4().hex},
            )
            connection.execute(
                text(
                    "INSERT INTO projects(id,name,owner_id,description) "
                    "VALUES (:id,'existing',:owner,'preserve')"
                ),
                {"id": project_id, "owner": owner_id},
            )
            connection.execute(
                text(
                    "INSERT INTO services(id,project_id,name,service_type,resources) "
                    "VALUES (:id,:project,'existing','web',CAST(:resources AS jsonb))"
                ),
                {"id": service_id, "project": project_id, "resources": '{"cpu":1,"memory_mb":512}'},
            )
            connection.execute(
                text(
                    "INSERT INTO api_credentials(id,user_id,token_hash,expires_at) "
                    "VALUES (:id,:owner,:digest,now()+INTERVAL '1 day')"
                ),
                {"id": credential_id, "owner": owner_id, "digest": uuid4().hex + uuid4().hex},
            )
        subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
        subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
        subprocess.run(["alembic", "check"], cwd=API_ROOT, check=True)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT owner_id,description FROM projects WHERE id=:id"), {"id": project_id}
            ).one() == (owner_id, "preserve")
            assert connection.execute(
                text("SELECT project_id,resources FROM services WHERE id=:id"), {"id": service_id}
            ).one() == (project_id, {"cpu": 1, "memory_mb": 512})
            assert (
                connection.execute(
                    text("SELECT user_id FROM api_credentials WHERE id=:id"), {"id": credential_id}
                ).scalar_one()
                == owner_id
            )
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0006"
            )
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM services WHERE id=:id"), {"id": service_id})
            connection.execute(
                text("DELETE FROM project_memberships WHERE project_id=:id"), {"id": project_id}
            )
            connection.execute(text("DELETE FROM projects WHERE id=:id"), {"id": project_id})
            connection.execute(
                text("DELETE FROM api_credentials WHERE id=:id"), {"id": credential_id}
            )
            connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": owner_id})
        subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
        engine.dispose()


@pytest.mark.integration
def test_tenancy_migration_preserves_browser_era_data_and_blocks_lossy_rollback():
    from test_control_plane import API_ROOT, require_disposable_database

    from lava.auth.passwords import hash_password

    require_disposable_database()
    subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
    subprocess.run(["alembic", "downgrade", "0003"], cwd=API_ROOT, check=True)
    engine = create_engine(os.environ["LAVA_DATABASE_URL"])
    owner_id, project_id, service_id, session_id = (str(uuid4()) for _ in range(4))
    account_name = "pre-tenancy-" + uuid4().hex
    password_hash = hash_password(secrets.token_urlsafe(32))
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users(id,name,is_active) VALUES (:id,:name,true)"),
                {"id": owner_id, "name": account_name},
            )
            connection.execute(
                text("INSERT INTO password_accounts(user_id,password_hash) VALUES (:id,:digest)"),
                {"id": owner_id, "digest": password_hash},
            )
            connection.execute(
                text("INSERT INTO projects(id,name,owner_id) VALUES (:id,:name,:owner)"),
                {"id": project_id, "name": "pre-tenancy", "owner": owner_id},
            )
            connection.execute(
                text(
                    "INSERT INTO services(id,project_id,name,service_type,resources) "
                    "VALUES (:id,:project,'web','web',CAST(:resources AS jsonb))"
                ),
                {"id": service_id, "project": project_id, "resources": '{"cpu":1,"memory_mb":512}'},
            )
            connection.execute(
                text(
                    "INSERT INTO browser_sessions(id,user_id,token_hash,expires_at) "
                    "VALUES (:id,:owner,:digest,:expiry)"
                ),
                {
                    "id": session_id,
                    "owner": owner_id,
                    "digest": secrets.token_hex(32),
                    "expiry": datetime.now(UTC) + timedelta(hours=1),
                },
            )
        subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
        subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
        subprocess.run(["alembic", "check"], cwd=API_ROOT, check=True)
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT password_hash FROM password_accounts WHERE user_id=:id"),
                    {"id": owner_id},
                ).scalar_one()
                == password_hash
            )
            assert (
                connection.execute(
                    text("SELECT user_id FROM browser_sessions WHERE id=:id"),
                    {"id": session_id},
                ).scalar_one()
                == owner_id
            )
            assert connection.execute(
                text("SELECT role,status FROM project_memberships WHERE project_id=:id"),
                {"id": project_id},
            ).one() == ("owner", "active")
            assert connection.execute(
                text(
                    "SELECT environment_id,build_method,config_revision FROM services WHERE id=:id"
                ),
                {"id": service_id},
            ).one() == (None, "railpack", 1)
        environment_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO environments(id,project_id,name,slug) "
                    "VALUES (:id,:project,'Development','development')"
                ),
                {"id": environment_id, "project": project_id},
            )
        result = subprocess.run(
            ["alembic", "downgrade", "0003"],
            cwd=API_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Downgrade refused" in result.stdout + result.stderr
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0006"
            )
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM services WHERE id=:id"), {"id": service_id})
            connection.execute(
                text("DELETE FROM environments WHERE project_id=:id"), {"id": project_id}
            )
            connection.execute(
                text("DELETE FROM project_memberships WHERE project_id=:id"), {"id": project_id}
            )
            connection.execute(text("DELETE FROM projects WHERE id=:id"), {"id": project_id})
            connection.execute(
                text("DELETE FROM browser_sessions WHERE id=:id"), {"id": session_id}
            )
            connection.execute(
                text("DELETE FROM password_accounts WHERE user_id=:id"), {"id": owner_id}
            )
            connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": owner_id})
        engine.dispose()


@pytest.mark.integration
def test_browser_migration_refuses_lossy_downgrade():
    import secrets

    from sqlalchemy import delete
    from sqlalchemy.orm import Session
    from test_control_plane import API_ROOT, require_disposable_database

    from lava.auth.accounts import provision_account
    from lava.db.base import PasswordAccount, User

    require_disposable_database()
    subprocess.run(["alembic", "upgrade", "head"], cwd=API_ROOT, check=True)
    engine = create_engine(os.environ["LAVA_DATABASE_URL"])
    with Session(engine, expire_on_commit=False) as session:
        user = provision_account(
            session, "migration-browser-" + uuid4().hex, secrets.token_urlsafe(32)
        )
        owner_id = user.id
    try:
        result = subprocess.run(
            ["alembic", "downgrade", "0002"], cwd=API_ROOT, capture_output=True, text=True
        )
        assert result.returncode != 0
        assert "Downgrade refused" in result.stdout + result.stderr
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0006"
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM password_accounts WHERE user_id=:id"),
                    {"id": owner_id},
                ).scalar_one()
                == 1
            )
    finally:
        with engine.begin() as connection:
            connection.execute(delete(PasswordAccount).where(PasswordAccount.user_id == owner_id))
            connection.execute(delete(User).where(User.id == owner_id))
        engine.dispose()
