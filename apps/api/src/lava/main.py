from contextlib import asynccontextmanager
from time import monotonic
from typing import Annotated
from uuid import uuid4

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from lava.core.logging import configure_logging
from lava.core.settings import Settings, get_settings


def check_database(settings: Annotated[Settings, Depends(get_settings)]) -> bool:
    engine = create_engine(
        settings.database_url.get_secret_value(), connect_args={"connect_timeout": 3}
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            # Readiness requires the current schema, not just an accepting TCP socket.
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            return revision == "0001"
    except SQLAlchemyError:
        structlog.get_logger().warning("database_unavailable")
        return False
    finally:
        engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings().log_level)
    yield


app = FastAPI(title="LAVA API", version="0.0.1", lifespan=lifespan)


@app.middleware("http")
async def log_request(request: Request, call_next):
    request_id = uuid4().hex
    started = monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    structlog.get_logger().info(
        "http_request",
        request_id=request_id,
        method=request.method,
        status_code=response.status_code,
        duration_ms=round((monotonic() - started) * 1000, 2),
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready(database_ready: Annotated[bool, Depends(check_database)]) -> JSONResponse:
    return JSONResponse(
        status_code=200 if database_ready else 503,
        content={"status": "ready" if database_ready else "unavailable"},
    )
