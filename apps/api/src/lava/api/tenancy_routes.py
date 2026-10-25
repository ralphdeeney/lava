"""Membership, invitation and environment HTTP contracts."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from lava.api.schemas import (
    EnvironmentCreate,
    EnvironmentPatch,
    EnvironmentView,
    ErrorResponse,
    InvitationView,
    MemberCreate,
    MemberPatch,
    MembershipView,
)
from lava.application.tenancy import Tenancy
from lava.auth.dependencies import current_user
from lava.db.base import User
from lava.persistence.database import get_session

router = APIRouter(
    tags=["collaboration"],
    responses={
        401: {"model": ErrorResponse, "description": "Authentication required"},
        403: {"model": ErrorResponse, "description": "Role cannot be granted"},
        404: {"model": ErrorResponse, "description": "Resource not found"},
        409: {"model": ErrorResponse, "description": "Resource state conflict"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
    },
)
Principal = Annotated[User, Depends(current_user)]
Database = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/projects/{project_id}/members", response_model=list[MembershipView])
def members(
    project_id: UUID, user: Principal, session: Database, limit: Limit = 50, offset: Offset = 0
):
    return Tenancy(session).members(user.id, str(project_id), limit, offset)


@router.post("/projects/{project_id}/members", response_model=MembershipView, status_code=201)
def add_member(project_id: UUID, body: MemberCreate, user: Principal, session: Database):
    return Tenancy(session).add_member(user.id, str(project_id), body.username, body.role)


@router.get("/projects/{project_id}/members/{membership_id}", response_model=MembershipView)
def member(project_id: UUID, membership_id: UUID, user: Principal, session: Database):
    control = Tenancy(session)
    control.access(user.id, str(project_id))
    return control.membership(str(project_id), str(membership_id))


@router.patch("/projects/{project_id}/members/{membership_id}", response_model=MembershipView)
def change_role(
    project_id: UUID, membership_id: UUID, body: MemberPatch, user: Principal, session: Database
):
    return Tenancy(session).change_role(user.id, str(project_id), str(membership_id), body.role)


@router.delete("/projects/{project_id}/members/{membership_id}", response_model=MembershipView)
def revoke_member(project_id: UUID, membership_id: UUID, user: Principal, session: Database):
    return Tenancy(session).revoke_member(user.id, str(project_id), str(membership_id))


@router.get("/projects/{project_id}/invitations", response_model=list[InvitationView])
def invitations(
    project_id: UUID, user: Principal, session: Database, limit: Limit = 50, offset: Offset = 0
):
    return Tenancy(session).invitations(user.id, str(project_id), limit, offset)


@router.post("/projects/{project_id}/invitations", response_model=InvitationView, status_code=201)
def invite(project_id: UUID, body: MemberCreate, user: Principal, session: Database):
    return Tenancy(session).invite(user.id, str(project_id), body.username, body.role)


@router.delete("/projects/{project_id}/invitations/{invitation_id}", response_model=InvitationView)
def revoke_invitation(project_id: UUID, invitation_id: UUID, user: Principal, session: Database):
    return Tenancy(session).revoke_invitation(user.id, str(project_id), str(invitation_id))


@router.get("/invitations", response_model=list[InvitationView])
def inbox(user: Principal, session: Database, limit: Limit = 50, offset: Offset = 0):
    return Tenancy(session).inbox(user.id, limit, offset)


@router.post("/invitations/{invitation_id}/accept", response_model=InvitationView)
def accept_invitation(invitation_id: UUID, user: Principal, session: Database):
    return Tenancy(session).decide_invitation(user.id, str(invitation_id), True)


@router.post("/invitations/{invitation_id}/decline", response_model=InvitationView)
def decline_invitation(invitation_id: UUID, user: Principal, session: Database):
    return Tenancy(session).decide_invitation(user.id, str(invitation_id), False)


@router.get("/projects/{project_id}/environments", response_model=list[EnvironmentView])
def environments(
    project_id: UUID, user: Principal, session: Database, limit: Limit = 50, offset: Offset = 0
):
    return Tenancy(session).environments(user.id, str(project_id), limit, offset)


@router.post("/projects/{project_id}/environments", response_model=EnvironmentView, status_code=201)
def create_environment(
    project_id: UUID, body: EnvironmentCreate, user: Principal, session: Database
):
    return Tenancy(session).create_environment(user.id, str(project_id), body.model_dump())


@router.get("/projects/{project_id}/environments/{environment_id}", response_model=EnvironmentView)
def get_environment(project_id: UUID, environment_id: UUID, user: Principal, session: Database):
    control = Tenancy(session)
    control.access(user.id, str(project_id))
    return control.environment(str(project_id), str(environment_id))


@router.patch(
    "/projects/{project_id}/environments/{environment_id}", response_model=EnvironmentView
)
def update_environment(
    project_id: UUID,
    environment_id: UUID,
    body: EnvironmentPatch,
    user: Principal,
    session: Database,
):
    return Tenancy(session).update_environment(
        user.id, str(project_id), str(environment_id), body.model_dump(exclude_unset=True)
    )


@router.delete(
    "/projects/{project_id}/environments/{environment_id}", response_model=EnvironmentView
)
def archive_environment(project_id: UUID, environment_id: UUID, user: Principal, session: Database):
    return Tenancy(session).archive_environment(user.id, str(project_id), str(environment_id))
