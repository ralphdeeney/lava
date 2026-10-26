from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
    environment_id: Mapped[str | None] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    build_method: Mapped[str] = mapped_column(String(20), nullable=False, server_default="railpack")
    start_command: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    deployment_branch: Mapped[str] = mapped_column(
        String(200), nullable=False, server_default="main"
    )
    config_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    desired_replicas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_services_project_name"),
        UniqueConstraint("project_id", "id", name="uq_services_project_id"),
        ForeignKeyConstraint(
            ["project_id", "environment_id"],
            ["environments.project_id", "environments.id"],
            name="fk_service_environment_same_project",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "service_type IN ('web', 'api', 'worker', 'database')", name="ck_services_type"
        ),
        CheckConstraint(
            "desired_state IN ('stopped', 'running', 'archived')", name="ck_services_state"
        ),
        CheckConstraint("length(trim(name)) > 0", name="ck_services_name"),
        CheckConstraint(
            "build_method IN ('railpack', 'dockerfile', 'image')", name="ck_services_build_method"
        ),
        CheckConstraint("config_revision >= 1", name="ck_services_config_revision"),
        CheckConstraint("desired_replicas BETWEEN 0 AND 10", name="ck_services_desired_replicas"),
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


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(foreign_keys=[user_id])

    @property
    def user_name(self) -> str:
        return self.user.name

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_membership_project_user"),
        CheckConstraint(
            "role IN ('owner','admin','developer','viewer')", name="ck_membership_role"
        ),
        CheckConstraint("status IN ('active','revoked')", name="ck_membership_status"),
        CheckConstraint(
            "(status='active' AND revoked_at IS NULL) OR "
            "(status='revoked' AND revoked_at IS NOT NULL)",
            name="ck_membership_revocation",
        ),
        Index("ix_membership_user_status", "user_id", "status"),
    )


class ProjectInvitation(Base):
    __tablename__ = "project_invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    invitee_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    inviter_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    invitee: Mapped[User] = relationship(foreign_keys=[invitee_id])
    project: Mapped[Project] = relationship(foreign_keys=[project_id])

    @property
    def invitee_name(self) -> str:
        return self.invitee.name

    @property
    def project_name(self) -> str:
        return self.project.name

    __table_args__ = (
        CheckConstraint("role IN ('admin','developer','viewer')", name="ck_invitation_role"),
        CheckConstraint(
            "status IN ('pending','accepted','declined','revoked','expired')",
            name="ck_invitation_status",
        ),
        CheckConstraint("expires_at > created_at", name="ck_invitation_expiry"),
        Index("ix_invitation_project_status", "project_id", "status"),
        Index("ix_invitation_invitee_status", "invitee_id", "status"),
        Index(
            "uq_pending_invitation_project_invitee",
            "project_id",
            "invitee_id",
            unique=True,
            postgresql_where=sa_text("status = 'pending'"),
        ),
    )


class Environment(Base):
    __tablename__ = "environments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, server_default="")
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
        UniqueConstraint("project_id", "slug", name="uq_environment_project_slug"),
        UniqueConstraint("project_id", "id", name="uq_environment_project_id"),
        CheckConstraint(
            "lifecycle_status IN ('active','archived')", name="ck_environment_lifecycle"
        ),
        CheckConstraint("slug ~ '^[a-z][a-z0-9-]{0,99}$'", name="ck_environment_slug"),
    )


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    environment_id: Mapped[str] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False
    )
    service_id: Mapped[str] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    repository_url: Mapped[str] = mapped_column(String(2048), nullable=False, server_default="")
    source_commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    source_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    image_digest: Mapped[str | None] = mapped_column(String(255))
    configuration_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
    transition_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint(
            "project_id", "service_id", "idempotency_key", name="uq_deployment_idempotency"
        ),
        ForeignKeyConstraint(
            ["project_id", "environment_id"],
            ["environments.project_id", "environments.id"],
            name="fk_deployment_environment_same_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "service_id"],
            ["services.project_id", "services.id"],
            name="fk_deployment_service_same_project",
            ondelete="RESTRICT",
        ),
        CheckConstraint("source_type IN ('git','image')", name="ck_deployment_source_type"),
        CheckConstraint(
            "status IN ('queued','building','built','deploying','verifying','active',"
            "'failed','cancelled','rolled_back')",
            name="ck_deployment_status",
        ),
        CheckConstraint(
            "source_commit_sha ~ '^[0-9a-fA-F]{7,64}$'", name="ck_deployment_commit_sha"
        ),
        CheckConstraint("configuration_revision >= 1", name="ck_deployment_config_revision"),
        CheckConstraint("transition_version >= 0", name="ck_deployment_transition_version"),
        Index("ix_deployments_status_created", "status", "created_at"),
        Index("ix_deployments_service_created", "service_id", "created_at"),
    )


class DeploymentEvent(Base):
    __tablename__ = "deployment_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    deployment_id: Mapped[str] = mapped_column(
        ForeignKey("deployments.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("deployment_id", "sequence", name="uq_deployment_event_sequence"),
        Index("ix_deployment_events_deployment_created", "deployment_id", "created_at", "id"),
    )


class DeploymentJob(Base):
    __tablename__ = "deployment_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    deployment_id: Mapped[str] = mapped_column(
        ForeignKey("deployments.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','retry_wait','succeeded','failed','cancelled')",
            name="ck_deployment_job_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10",
            name="ck_deployment_job_attempts",
        ),
        CheckConstraint("lease_generation >= 0", name="ck_deployment_job_generation"),
        Index("ix_deployment_jobs_schedule", "status", "available_at", "priority"),
    )


class BuildArtifact(Base):
    __tablename__ = "build_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    deployment_id: Mapped[str] = mapped_column(
        ForeignKey("deployments.id", ondelete="RESTRICT"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    source_commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    railpack_version: Mapped[str] = mapped_column(String(40), nullable=False)
    buildkit_version: Mapped[str] = mapped_column(String(40), nullable=False)
    image_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("deployment_id", "attempt", name="uq_build_artifact_attempt"),
        CheckConstraint("attempt >= 1", name="ck_build_artifact_attempt"),
        CheckConstraint("image_digest ~ '^sha256:[0-9a-f]{64}$'", name="ck_build_artifact_digest"),
    )


class PasswordAccount(Base):
    __tablename__ = "password_accounts"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_browser_sessions_expiry"),
    )


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    bucket_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("attempts > 0", name="ck_login_attempts_positive"),)


class BuildExecution(Base):
    __tablename__ = "build_executions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("deployment_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    deployment_id: Mapped[str] = mapped_column(
        ForeignKey("deployments.id", ondelete="RESTRICT"), nullable=False
    )
    claim_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    source_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    configuration_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    fixture: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="controlled-probe")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="UNKNOWN")
    image_digest: Mapped[str | None] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        UniqueConstraint("job_id", "claim_generation", name="uq_build_execution_claim"),
        Index("ix_build_executions_job", "job_id"),
        CheckConstraint(
            "status IN ('UNKNOWN','RUNNING','COMPLETED','CANCELLED','FAILED')",
            name="ck_build_execution_status",
        ),
    )


class BuildRequestNonce(Base):
    __tablename__ = "build_request_nonces"
    nonce_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("build_executions.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_build_request_nonces_expiry", "expires_at"),)
