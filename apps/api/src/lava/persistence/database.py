"""Request-scoped sessions; adapters never perform infrastructure operations."""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from lava.core.settings import Settings, get_settings


@lru_cache(maxsize=4)
def engine_for_url(url: str) -> Engine:
    return create_engine(url, connect_args={"connect_timeout": 3}, pool_pre_ping=True)


def get_session(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[Session]:
    with Session(engine_for_url(settings.database_url.get_secret_value())) as session:
        yield session
