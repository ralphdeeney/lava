"""Provision the limited local worker role after migrations run."""

import os

import psycopg
from psycopg import sql

from lava.core.settings import get_settings


def provision(connection, password: str, role: str = "lava_worker") -> None:
    if len(password) < 24:
        raise RuntimeError("Worker password must be at least 24 characters")
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        action = "ALTER" if cursor.fetchone() else "CREATE"
        cursor.execute(
            sql.SQL(action + " ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        for statement in (
            "GRANT USAGE ON SCHEMA public TO {}",
            "GRANT SELECT, UPDATE ON deployment_jobs, deployments TO {}",
            "GRANT SELECT, INSERT ON deployment_events, build_artifacts TO {}",
            "GRANT SELECT ON build_executions TO {}",
            "REVOKE CREATE ON SCHEMA public FROM {}",
        ):
            cursor.execute(sql.SQL(statement).format(sql.Identifier(role)))


def main() -> None:
    password = os.environ.get("POSTGRES_WORKER_PASSWORD", "")
    database_url = (
        get_settings()
        .database_url.get_secret_value()
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with psycopg.connect(database_url) as connection:
        provision(connection, password)


if __name__ == "__main__":
    main()
