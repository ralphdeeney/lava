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
