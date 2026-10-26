from contextlib import asynccontextmanager
from time import monotonic
from typing import Annotated
from uuid import uuid4

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from lava.api.routes import router
from lava.api.tenancy_routes import router as tenancy_router
from lava.auth.routes import router as auth_router
from lava.core.logging import configure_logging
from lava.core.settings import Settings, get_settings
from lava.domain.control_plane import ControlPlaneError


def check_database(settings: Annotated[Settings, Depends(get_settings)]) -> bool:
    engine = create_engine(
        settings.database_url.get_secret_value(), connect_args={"connect_timeout": 3}
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            # Readiness requires the current schema, not just an accepting TCP socket.
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            return revision == "0008"
    except SQLAlchemyError:
        structlog.get_logger().warning("database_unavailable")
        return False
    finally:
        engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings().log_level)
    yield


app = FastAPI(title="LAVA API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_request(request: Request, call_next):
    request_id = uuid4().hex
    started = monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    if request.url.path.startswith("/auth/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
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


@app.exception_handler(ControlPlaneError)
def control_error(request: Request, error: ControlPlaneError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={"error": {"code": error.code, "message": error.message}},
        headers={"WWW-Authenticate": "Bearer"} if error.status == 401 else None,
    )


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    # Never echo arbitrary request input, credential-like field names or validation context.
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_error", "message": "Invalid request"}},
    )


@app.exception_handler(SQLAlchemyError)
def persistence_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
    structlog.get_logger().warning("control_plane_database_unavailable")
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "unavailable", "message": "Service temporarily unavailable"}},
    )


app.include_router(router)
app.include_router(tenancy_router)

app.include_router(auth_router)
