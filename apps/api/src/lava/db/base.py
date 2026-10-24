from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

LEGACY_OWNER_ID = "00000000-0000-0000-0000-000000000000"


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApiCredential(Base):
    __tablename__ = "api_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("expires_at > created_at", name="ck_credentials_expiry"),)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, server_default="")
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_projects_owner_name"),
        CheckConstraint("lifecycle_status IN ('active', 'archived')", name="ck_projects_lifecycle"),
        CheckConstraint("length(trim(name)) > 0", name="ck_projects_name"),
    )


class Service(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    service_type: Mapped[str] = mapped_column(String(20), nullable=False)
    desired_state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="stopped")
    resources: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_services_project_name"),
        CheckConstraint(
            "service_type IN ('web', 'api', 'worker', 'database')", name="ck_services_type"
        ),
        CheckConstraint(
            "desired_state IN ('stopped', 'running', 'archived')", name="ck_services_state"
        ),
        CheckConstraint("length(trim(name)) > 0", name="ck_services_name"),
        CheckConstraint(
            "jsonb_typeof(resources) = 'object' "
            "AND resources ? 'cpu' AND resources ? 'memory_mb' "
            "AND jsonb_typeof(resources->'cpu') = 'number' "
            "AND jsonb_typeof(resources->'memory_mb') = 'number' "
            "AND (resources->>'cpu')::numeric > 0 "
            "AND (resources->>'cpu')::numeric <= 16 "
            "AND (resources->>'memory_mb')::numeric >= 64 "
            "AND (resources->>'memory_mb')::numeric <= 65536 "
            "AND (resources->>'memory_mb')::numeric = "
            "trunc((resources->>'memory_mb')::numeric)",
            name="ck_services_resources",
        ),
    )
