from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from lava.api.schemas import (
    DeploymentCreate,
    DeploymentEventView,
    DeploymentView,
    ErrorResponse,
    ProjectCreate,
    ProjectPatch,
    ProjectView,
    ServiceCreate,
    ServicePatch,
    ServiceView,
)
from lava.application.control_plane import ControlPlane
from lava.application.deployments import DeploymentService
from lava.application.tenancy import Tenancy
from lava.auth.dependencies import current_user
from lava.db.base import Deployment, DeploymentEvent, Service, User
from lava.persistence.database import get_session

router = APIRouter(
    tags=["control-plane"],
    responses={
        401: {"model": ErrorResponse, "description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Resource not found"},
        409: {"model": ErrorResponse, "description": "Resource state conflict"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Persistence unavailable"},
    },
)
Principal = Annotated[User, Depends(current_user)]
Database = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def project_view(project, role: str) -> dict:
    return {
        "id": project.id,
        "owner_id": project.owner_id,
        "name": project.name,
        "description": project.description,
        "lifecycle_status": project.lifecycle_status,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "my_role": role,
    }


@router.post("/projects", response_model=ProjectView, status_code=201)
def create_project(body: ProjectCreate, user: Principal, session: Database):
    return project_view(
        ControlPlane(session).create_project(user.id, body.name, body.description), "owner"
    )


@router.get("/projects", response_model=list[ProjectView])
def list_projects(user: Principal, session: Database, limit: Limit = 50, offset: Offset = 0):
    tenancy = Tenancy(session)
    return [
        project_view(project, tenancy.access(user.id, project.id)[1])
        for project in tenancy.projects(user.id, limit, offset)
    ]


@router.get("/projects/{project_id}", response_model=ProjectView)
def get_project(project_id: UUID, user: Principal, session: Database):
    return project_view(*Tenancy(session).access(user.id, str(project_id)))


@router.patch("/projects/{project_id}", response_model=ProjectView)
def update_project(project_id: UUID, body: ProjectPatch, user: Principal, session: Database):
    return project_view(
        ControlPlane(session).update_project(
            user.id, str(project_id), body.model_dump(exclude_unset=True)
        ),
        "owner",
    )


@router.delete("/projects/{project_id}", response_model=ProjectView)
def archive_project(project_id: UUID, user: Principal, session: Database):
    return project_view(ControlPlane(session).archive_project(user.id, str(project_id)), "owner")


@router.post("/projects/{project_id}/services", response_model=ServiceView, status_code=201)
def create_service(project_id: UUID, body: ServiceCreate, user: Principal, session: Database):
    return ControlPlane(session).create_service(
        user.id, str(project_id), body.model_dump(exclude_none=True)
    )


@router.get("/projects/{project_id}/services", response_model=list[ServiceView])
def list_services(
    project_id: UUID, user: Principal, session: Database, limit: Limit = 50, offset: Offset = 0
):
    control = ControlPlane(session)
    project, _ = control.tenancy.access(user.id, str(project_id))
    return control.repository.services(project.id, limit, offset)


@router.get("/projects/{project_id}/services/{service_id}", response_model=ServiceView)
def get_service(project_id: UUID, service_id: UUID, user: Principal, session: Database):
    control = ControlPlane(session)
    project, _ = control.tenancy.access(user.id, str(project_id))
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


@router.post(
    "/projects/{project_id}/services/{service_id}/deployments",
    response_model=DeploymentView,
    status_code=201,
)
def create_deployment(
    project_id: UUID, service_id: UUID, body: DeploymentCreate, user: Principal, session: Database
):
    return DeploymentService(session).create(
        user.id, str(project_id), str(service_id), body.model_dump()
    )


@router.get(
    "/projects/{project_id}/services/{service_id}/deployments", response_model=list[DeploymentView]
)
def list_deployments(
    project_id: UUID,
    service_id: UUID,
    user: Principal,
    session: Database,
    limit: Limit = 50,
    offset: Offset = 0,
):
    control = DeploymentService(session)
    project, _ = control.tenancy.access(user.id, str(project_id))
    service = session.scalar(
        select(Service).where(Service.id == str(service_id), Service.project_id == project.id)
    )
    if service is None:
        from lava.domain.control_plane import ControlPlaneError

        raise ControlPlaneError(404, "not_found", "Resource not found")
    return list(
        session.scalars(
            select(Deployment)
            .where(Deployment.project_id == project.id, Deployment.service_id == service.id)
            .order_by(Deployment.created_at.desc(), Deployment.id)
            .limit(limit)
            .offset(offset)
        )
    )


@router.get(
    "/projects/{project_id}/services/{service_id}/deployments/{deployment_id}",
    response_model=DeploymentView,
)
def get_deployment(
    project_id: UUID, service_id: UUID, deployment_id: UUID, user: Principal, session: Database
):
    control = DeploymentService(session)
    project, _ = control.tenancy.access(user.id, str(project_id))
    deployment = session.scalar(
        select(Deployment).where(
            Deployment.id == str(deployment_id),
            Deployment.project_id == project.id,
            Deployment.service_id == str(service_id),
        )
    )
    if deployment is None:
        from lava.domain.control_plane import ControlPlaneError

        raise ControlPlaneError(404, "not_found", "Resource not found")
    return deployment


@router.get(
    "/projects/{project_id}/services/{service_id}/deployments/{deployment_id}/events",
    response_model=list[DeploymentEventView],
)
def deployment_events(
    project_id: UUID, service_id: UUID, deployment_id: UUID, user: Principal, session: Database
):
    deployment = get_deployment(project_id, service_id, deployment_id, user, session)
    return list(
        session.scalars(
            select(DeploymentEvent)
            .where(DeploymentEvent.deployment_id == deployment.id)
            .order_by(DeploymentEvent.created_at, DeploymentEvent.id)
        )
    )
