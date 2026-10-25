import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lava.auth.credentials import NAME_PATTERN
from lava.domain.control_plane import DesiredState, ProjectStatus, ServiceType

Name = Annotated[str, Field(min_length=1, max_length=100)]
MemberRole = Literal["owner", "admin", "developer", "viewer"]
AssignableRole = Literal["admin", "developer", "viewer"]
BuildMethod = Literal["railpack", "dockerfile", "image"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def reject_null(cls, value):
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("Null fields are not supported")
        return value

    @field_validator("name", check_fields=False)
    @classmethod
    def name_valid(cls, value: str) -> str:
        value = value.strip()
        if not NAME_PATTERN.fullmatch(value):
            raise ValueError("Name must contain safe printable characters")
        return value


class ProjectCreate(Input):
    name: Name
    description: str = Field(default="", max_length=2000)


class ProjectPatch(Input):
    name: Name | None = None
    description: str | None = Field(default=None, max_length=2000)


class Resources(Input):
    cpu: float = Field(default=1.0, gt=0, le=16, strict=True, allow_inf_nan=False)
    memory_mb: int = Field(default=512, ge=64, le=65536, strict=True)


class ServiceCreate(Input):
    name: Name
    service_type: ServiceType
    desired_state: Literal["stopped", "running"] = "stopped"
    resources: Resources = Field(default_factory=Resources)
    environment_id: UUID | None = None
    build_method: BuildMethod = "railpack"
    start_command: str = Field(default="", max_length=500)
    deployment_branch: str = Field(default="main", min_length=1, max_length=200)
    desired_replicas: int = Field(default=1, ge=0, le=10, strict=True)

    @field_validator("start_command")
    @classmethod
    def command_valid(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Start command contains control characters")
        return value

    @field_validator("deployment_branch")
    @classmethod
    def branch_valid(cls, value: str) -> str:
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", value)
            or ".." in value
            or "//" in value
            or value.endswith(("/", ".", ".lock"))
        ):
            raise ValueError("Invalid branch reference")
        return value


class ServicePatch(Input):
    name: Name | None = None
    service_type: ServiceType | None = None
    desired_state: Literal["stopped", "running"] | None = None
    resources: Resources | None = None
    environment_id: UUID | None = None
    build_method: BuildMethod | None = None
    start_command: str | None = Field(default=None, max_length=500)
    deployment_branch: str | None = Field(default=None, min_length=1, max_length=200)
    desired_replicas: int | None = Field(default=None, ge=0, le=10, strict=True)

    @model_validator(mode="before")
    @classmethod
    def reject_null(cls, value):
        if isinstance(value, dict) and any(
            item is None for key, item in value.items() if key != "environment_id"
        ):
            raise ValueError("Null fields are not supported")
        return value

    _command_valid = field_validator("start_command")(ServiceCreate.command_valid.__func__)
    _branch_valid = field_validator("deployment_branch")(ServiceCreate.branch_valid.__func__)


class ProjectView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: UUID
    name: str
    description: str
    lifecycle_status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    my_role: MemberRole


class ServiceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    name: str
    service_type: ServiceType
    desired_state: DesiredState
    resources: Resources
    environment_id: UUID | None
    build_method: BuildMethod
    start_command: str
    deployment_branch: str
    config_revision: int
    desired_replicas: int
    created_at: datetime
    updated_at: datetime


class MemberCreate(Input):
    username: Name
    role: AssignableRole


class MemberPatch(Input):
    role: AssignableRole


class MembershipView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    user_id: UUID
    user_name: str
    role: MemberRole
    status: Literal["active", "revoked"]
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


class InvitationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    project_name: str
    invitee_id: UUID
    invitee_name: str
    role: AssignableRole
    status: Literal["pending", "accepted", "declined", "revoked", "expired"]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class EnvironmentCreate(Input):
    name: Name
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9-]*$")
    description: str = Field(default="", max_length=2000)


class EnvironmentPatch(Input):
    name: Name | None = None
    slug: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9-]*$"
    )
    description: str | None = Field(default=None, max_length=2000)


class EnvironmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    name: str
    slug: str
    description: str
    lifecycle_status: Literal["active", "archived"]
    created_at: datetime
    updated_at: datetime


class DeploymentCreate(Input):
    environment_id: UUID
    source_type: Literal["git", "image"] = "git"
    repository_url: str = Field(default="", max_length=2048)
    source_commit_sha: str = Field(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]{7,64}$")
    source_branch: str = Field(default="main", min_length=1, max_length=200)
    image_digest: str | None = Field(default=None, max_length=255)
    configuration_revision: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=128)


class DeploymentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    environment_id: UUID
    service_id: UUID
    source_type: Literal["git", "image"]
    repository_url: str
    source_commit_sha: str
    source_branch: str
    image_digest: str | None
    configuration_revision: int
    idempotency_key: str
    status: Literal[
        "queued",
        "building",
        "built",
        "deploying",
        "verifying",
        "active",
        "failed",
        "cancelled",
        "rolled_back",
    ]
    failure_code: str | None
    failure_message: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DeploymentEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    deployment_id: UUID
    from_status: str | None
    to_status: str
    message: str | None
    created_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
