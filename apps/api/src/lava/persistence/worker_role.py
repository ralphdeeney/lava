"""Provision the limited local worker role after migrations run."""

import os

import psycopg
from psycopg import sql

from lava.core.settings import get_settings


def main() -> None:
    password = os.environ.get("POSTGRES_WORKER_PASSWORD")
    if not password or len(password) < 24:
        raise RuntimeError("POSTGRES_WORKER_PASSWORD must be at least 24 characters")
    database_url = (
        get_settings()
        .database_url.get_secret_value()
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'lava_worker'")
            if cursor.fetchone():
                cursor.execute(
                    sql.SQL("ALTER ROLE lava_worker PASSWORD {}").format(sql.Literal(password))
                )
            else:
                cursor.execute(
                    sql.SQL("CREATE ROLE lava_worker LOGIN PASSWORD {}").format(
                        sql.Literal(password)
                    )
                )
            cursor.execute("GRANT USAGE ON SCHEMA public TO lava_worker")
            cursor.execute("GRANT SELECT, UPDATE ON deployment_jobs TO lava_worker")
            cursor.execute("GRANT SELECT, UPDATE ON deployments TO lava_worker")
            cursor.execute("GRANT SELECT, INSERT ON deployment_events TO lava_worker")
            cursor.execute("GRANT SELECT, INSERT ON build_artifacts TO lava_worker")
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM lava_worker")


if __name__ == "__main__":
    main()
