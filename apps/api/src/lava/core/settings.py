from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LAVA_", extra="ignore", hide_input_in_errors=True)
    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr

    @field_validator("database_url")
    @classmethod
    def postgres_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            if url.drivername != "postgresql+psycopg" or not url.host or not url.database:
                raise ValueError
        except Exception:
            raise ValueError(
                "database_url must be a PostgreSQL psycopg URL with host and database"
            ) from None
        return value

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    browser_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    session_ttl_seconds: int = 3600
    worker_poll_interval_seconds: float = 1.0
    worker_lease_seconds: int = 60
    worker_heartbeat_interval_seconds: int = 15
    worker_max_attempts: int = 3
    worker_shutdown_grace_seconds: int = 20
    worker_concurrency: int = 1
    worker_retry_backoff_seconds: float = 1.0
    worker_executor_mode: Literal["simulated", "controlled-probe", "fixture-build"] = "simulated"
    executor_socket: str = ""
    executor_key_file: str = ""
    executor_fixture: Literal["python", "node", "go"] = "python"

    @model_validator(mode="after")
    def safe_executor(self):
        if self.worker_executor_mode in {"controlled-probe", "fixture-build"}:
            if self.worker_executor_mode == "controlled-probe" and self.environment != "test":
                raise ValueError("Controlled probes require the test environment")
            if not self.executor_socket.startswith("/") or not self.executor_key_file.startswith(
                "/"
            ):
                raise ValueError("Executor socket and key must be absolute paths")
        return self

    @model_validator(mode="after")
    def safe_worker_timing(self):
        if not 0.1 <= self.worker_poll_interval_seconds <= 60:
            raise ValueError("worker poll interval must be between 0.1 and 60 seconds")
        if not 3 <= self.worker_lease_seconds <= 3600:
            raise ValueError("worker lease must be between 3 and 3600 seconds")
        if not 0.5 <= self.worker_heartbeat_interval_seconds < self.worker_lease_seconds / 3:
            raise ValueError(
                "worker heartbeat must be at least 0.5 seconds and below one third of the lease"
            )
        if not 1 <= self.worker_max_attempts <= 10:
            raise ValueError("worker attempts must be between 1 and 10")
        if self.worker_concurrency != 1:
            raise ValueError("only one worker thread per process is supported")
        if not 0.1 <= self.worker_retry_backoff_seconds <= 300:
            raise ValueError("worker backoff must be between 0.1 and 300 seconds")
        if not 1 <= self.worker_shutdown_grace_seconds <= 300:
            raise ValueError("worker shutdown grace must be between 1 and 300 seconds")
        return self

    @field_validator("browser_origin")
    @classmethod
    def valid_browser_origin(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.port == 0
            ):
                raise ValueError
        except ValueError:
            raise ValueError(
                "browser_origin must be an HTTP(S) origin without credentials or path"
            ) from None
        return value

    @field_validator("session_ttl_seconds")
    @classmethod
    def bounded_session_lifetime(cls, value: int) -> int:
        if not 60 <= value <= 86400:
            raise ValueError("session_ttl_seconds must be between 60 and 86400")
        return value

    @model_validator(mode="after")
    def production_browser_security(self):
        if self.browser_origin.startswith("https://") and not self.cookie_secure:
            raise ValueError("HTTPS browser origins require Secure cookies")
        if self.environment == "production" and (
            not self.cookie_secure or not self.browser_origin.startswith("https://")
        ):
            raise ValueError("Production requires Secure cookies and an HTTPS browser origin")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


class ExecutorSettings(BaseSettings):
    """Executor-only configuration; never receives API or migration credentials."""

    model_config = SettingsConfigDict(
        env_prefix="LAVA_EXECUTOR_", extra="ignore", hide_input_in_errors=True
    )
    database_url: SecretStr
    database_role: str = "lava_executor"

    @model_validator(mode="after")
    def runtime_database(self):
        url = make_url(self.database_url.get_secret_value())
        if (
            url.drivername != "postgresql+psycopg"
            or not url.host
            or not url.database
            or url.username != self.database_role
        ):
            raise ValueError("Executor requires its dedicated PostgreSQL role")
        return self
