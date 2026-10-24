from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lava.auth.credentials import NAME_PATTERN
from lava.domain.control_plane import DesiredState, ProjectStatus, ServiceType

Name = Annotated[str, Field(min_length=1, max_length=100)]


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


class ServicePatch(Input):
    name: Name | None = None
    service_type: ServiceType | None = None
    desired_state: Literal["stopped", "running"] | None = None
    resources: Resources | None = None


class ProjectView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: UUID
    name: str
    description: str
    lifecycle_status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class ServiceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    name: str
    service_type: ServiceType
    desired_state: DesiredState
    resources: Resources
    created_at: datetime
    updated_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
