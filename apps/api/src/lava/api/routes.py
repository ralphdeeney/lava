from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from lava.api.schemas import (
    ProjectCreate,
    ProjectPatch,
    ProjectView,
    ServiceCreate,
    ServicePatch,
    ServiceView,
)
from lava.application.control_plane import ControlPlane
from lava.auth.dependencies import current_user
from lava.db.base import User
from lava.persistence.database import get_session

router = APIRouter(tags=["control-plane"])
Principal = Annotated[User, Depends(current_user)]
Database = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post("/projects", response_model=ProjectView, status_code=201)
def create_project(body: ProjectCreate, user: Principal, session: Database):
    return ControlPlane(session).create_project(user.id, body.name, body.description)


@router.get("/projects", response_model=list[ProjectView])
def list_projects(user: Principal, session: Database, limit: Limit = 50, offset: Offset = 0):
    return ControlPlane(session).repository.projects(user.id, limit, offset)


@router.get("/projects/{project_id}", response_model=ProjectView)
def get_project(project_id: UUID, user: Principal, session: Database):
    return ControlPlane(session).repository.project(user.id, str(project_id))


@router.patch("/projects/{project_id}", response_model=ProjectView)
def update_project(project_id: UUID, body: ProjectPatch, user: Principal, session: Database):
    return ControlPlane(session).update_project(
        user.id, str(project_id), body.model_dump(exclude_unset=True)
    )


@router.delete("/projects/{project_id}", response_model=ProjectView)
def archive_project(project_id: UUID, user: Principal, session: Database):
    return ControlPlane(session).archive_project(user.id, str(project_id))


@router.post("/projects/{project_id}/services", response_model=ServiceView, status_code=201)
def create_service(project_id: UUID, body: ServiceCreate, user: Principal, session: Database):
    return ControlPlane(session).create_service(user.id, str(project_id), body.model_dump())


@router.get("/projects/{project_id}/services", response_model=list[ServiceView])
def list_services(
    project_id: UUID, user: Principal, session: Database, limit: Limit = 50, offset: Offset = 0
):
    control = ControlPlane(session)
    project = control.repository.project(user.id, str(project_id))
    return control.repository.services(project.id, limit, offset)


@router.get("/projects/{project_id}/services/{service_id}", response_model=ServiceView)
def get_service(project_id: UUID, service_id: UUID, user: Principal, session: Database):
    control = ControlPlane(session)
    project = control.repository.project(user.id, str(project_id))
    return control.repository.service(project.id, str(service_id))


@router.patch("/projects/{project_id}/services/{service_id}", response_model=ServiceView)
def update_service(
    project_id: UUID, service_id: UUID, body: ServicePatch, user: Principal, session: Database
):
    return ControlPlane(session).update_service(
        user.id, str(project_id), str(service_id), body.model_dump(exclude_unset=True)
    )


@router.delete("/projects/{project_id}/services/{service_id}", response_model=ServiceView)
def archive_service(project_id: UUID, service_id: UUID, user: Principal, session: Database):
    return ControlPlane(session).archive_service(user.id, str(project_id), str(service_id))
