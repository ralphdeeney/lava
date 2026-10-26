"""Provision a build executor runtime role without migration or account authority."""

import os

import psycopg
from psycopg import sql

from lava.core.settings import get_settings


def provision(connection, password: str, role: str = "lava_executor") -> None:
    if len(password) < 24:
        raise ValueError("Executor password must contain at least 24 characters")
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
            "GRANT SELECT ON deployment_jobs, deployments, "
            "build_executions, build_request_nonces TO {}",
            "GRANT UPDATE (cancellation_requested_at, updated_at) ON deployment_jobs TO {}",
            "GRANT INSERT ON build_executions, build_request_nonces TO {}",
            "GRANT UPDATE (status, image_digest, updated_at) ON build_executions TO {}",
            "GRANT DELETE ON build_request_nonces TO {}",
            "REVOKE CREATE ON SCHEMA public FROM {}",
        ):
            cursor.execute(sql.SQL(statement).format(sql.Identifier(role)))


def main() -> None:
    settings = get_settings()
    password = os.environ.get("POSTGRES_EXECUTOR_PASSWORD", "")
    url = settings.database_url.get_secret_value().replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(url) as connection:
        provision(connection, password)


if __name__ == "__main__":
    main()
