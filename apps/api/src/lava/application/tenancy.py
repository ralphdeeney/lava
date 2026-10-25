"""Project-scoped authorization and collaboration metadata transactions.

Every write locks the project first, so concurrent membership changes and resource
writes serialize on one row. Owner identity is the immutable projects.owner_id.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lava.db.base import Environment, Project, ProjectInvitation, ProjectMembership, User
from lava.domain.control_plane import ControlPlaneError

PERMISSIONS = {
    "owner": frozenset(
        {"read", "project_write", "service_write", "environment_write", "membership_write"}
    ),
    "admin": frozenset({"read", "service_write", "environment_write", "membership_write"}),
    "developer": frozenset({"read", "service_write", "environment_write"}),
    "viewer": frozenset({"read"}),
}
ASSIGNABLE = {
    "owner": frozenset({"admin", "developer", "viewer"}),
    "admin": frozenset({"admin", "developer", "viewer"}),
}


def conflict() -> ControlPlaneError:
    return ControlPlaneError(409, "conflict", "Resource conflicts with existing state")


def missing() -> ControlPlaneError:
    return ControlPlaneError(404, "not_found", "Resource not found")


class Tenancy:
    def __init__(self, session: Session):
        self.session = session

    def commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise conflict() from None

    def access(
        self,
        user_id: str,
        project_id: str,
        permission: str = "read",
        *,
        lock: bool = False,
        require_active: bool = True,
    ) -> tuple[Project, str]:
        query = select(Project).where(Project.id == project_id)
        if lock:
            query = query.with_for_update()
        project = self.session.scalar(query)
        if project is None:
            raise missing()
        membership = self.session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user_id,
                ProjectMembership.status == "active",
            )
        )
        if membership is None or permission not in PERMISSIONS.get(membership.role, ()):
            raise missing()
        # The canonical owner cannot be substituted by a forged membership row.
        if (membership.role == "owner") != (project.owner_id == user_id):
            raise missing()
        if lock and require_active and project.lifecycle_status != "active":
            raise ControlPlaneError(409, "archived", "Archived resources cannot be modified")
        return project, membership.role

    def projects(self, user_id: str, limit: int, offset: int) -> list[Project]:
        return list(
            self.session.scalars(
                select(Project)
                .join(ProjectMembership, ProjectMembership.project_id == Project.id)
                .where(
                    ProjectMembership.user_id == user_id,
                    ProjectMembership.status == "active",
                    or_(
                        and_(ProjectMembership.role == "owner", Project.owner_id == user_id),
                        and_(ProjectMembership.role != "owner", Project.owner_id != user_id),
                    ),
                )
                .order_by(Project.created_at, Project.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def membership(
        self, project_id: str, membership_id: str, *, lock: bool = False
    ) -> ProjectMembership:
        query = select(ProjectMembership).where(
            ProjectMembership.id == membership_id, ProjectMembership.project_id == project_id
        )
        if lock:
            query = query.with_for_update()
        member = self.session.scalar(query)
        if member is None:
            raise missing()
        return member

    def members(
        self, user_id: str, project_id: str, limit: int, offset: int
    ) -> list[ProjectMembership]:
        self.access(user_id, project_id)
        return list(
            self.session.scalars(
                select(ProjectMembership)
                .where(
                    ProjectMembership.project_id == project_id, ProjectMembership.status == "active"
                )
                .order_by(ProjectMembership.created_at, ProjectMembership.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def add_member(
        self, actor_id: str, project_id: str, username: str, role: str
    ) -> ProjectMembership:
        _, actor_role = self.access(actor_id, project_id, "membership_write", lock=True)
        if role not in ASSIGNABLE[actor_role]:
            raise ControlPlaneError(403, "forbidden", "Role cannot be assigned")
        target = self.session.scalar(
            select(User).where(User.name == username, User.is_active.is_(True))
        )
        if target is None:
            raise missing()
        existing = self.session.scalar(
            select(ProjectMembership)
            .where(
                ProjectMembership.project_id == project_id, ProjectMembership.user_id == target.id
            )
            .with_for_update()
        )
        if existing and existing.status == "active":
            raise conflict()
        if existing:
            existing.status, existing.role, existing.revoked_at = "active", role, None
            member = existing
        else:
            member = ProjectMembership(project_id=project_id, user_id=target.id, role=role)
            self.session.add(member)
        self.session.execute(
            update(ProjectInvitation)
            .where(
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.invitee_id == target.id,
                ProjectInvitation.status == "pending",
            )
            .values(status="revoked")
        )
        self.commit()
        return member

    def change_role(
        self, actor_id: str, project_id: str, membership_id: str, role: str
    ) -> ProjectMembership:
        _, actor_role = self.access(actor_id, project_id, "membership_write", lock=True)
        member = self.membership(project_id, membership_id, lock=True)
        if member.role == "owner" or member.status != "active":
            raise conflict()
        if role not in ASSIGNABLE[actor_role]:
            raise ControlPlaneError(403, "forbidden", "Role cannot be assigned")
        member.role = role
        if role not in ASSIGNABLE:
            self.session.execute(
                update(ProjectInvitation)
                .where(
                    ProjectInvitation.project_id == project_id,
                    ProjectInvitation.inviter_id == member.user_id,
                    ProjectInvitation.status == "pending",
                )
                .values(status="revoked")
            )
        self.commit()
        return member

    def revoke_member(
        self, actor_id: str, project_id: str, membership_id: str
    ) -> ProjectMembership:
        self.access(actor_id, project_id, "membership_write", lock=True, require_active=False)
        member = self.membership(project_id, membership_id, lock=True)
        if member.role == "owner":
            raise conflict()
        if member.status != "revoked":
            member.status, member.revoked_at = "revoked", datetime.now(UTC)
            self.session.execute(
                update(ProjectInvitation)
                .where(
                    ProjectInvitation.project_id == project_id,
                    ProjectInvitation.status == "pending",
                    (ProjectInvitation.invitee_id == member.user_id)
                    | (ProjectInvitation.inviter_id == member.user_id),
                )
                .values(status="revoked")
            )
            self.commit()
        return member

    def invitation(
        self, project_id: str, invitation_id: str, *, lock: bool = False
    ) -> ProjectInvitation:
        query = select(ProjectInvitation).where(
            ProjectInvitation.id == invitation_id, ProjectInvitation.project_id == project_id
        )
        if lock:
            query = query.with_for_update()
        invitation = self.session.scalar(query)
        if invitation is None:
            raise missing()
        return invitation

    def invite(self, actor_id: str, project_id: str, username: str, role: str) -> ProjectInvitation:
        _, actor_role = self.access(actor_id, project_id, "membership_write", lock=True)
        if role not in ASSIGNABLE[actor_role]:
            raise ControlPlaneError(403, "forbidden", "Role cannot be assigned")
        target = self.session.scalar(
            select(User).where(User.name == username, User.is_active.is_(True))
        )
        if target is None:
            raise missing()
        member = self.session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id, ProjectMembership.user_id == target.id
            )
        )
        if member and member.status == "active":
            raise conflict()
        previous = self.session.scalar(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.invitee_id == target.id,
                ProjectInvitation.status == "pending",
            )
            .with_for_update()
        )
        if previous:
            if previous.expires_at > datetime.now(UTC):
                raise conflict()
            previous.status = "expired"
            self.session.flush()
        invitation = ProjectInvitation(
            project_id=project_id,
            invitee_id=target.id,
            inviter_id=actor_id,
            role=role,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self.session.add(invitation)
        self.commit()
        return invitation

    def invitations(
        self, actor_id: str, project_id: str, limit: int, offset: int
    ) -> list[ProjectInvitation]:
        self.access(actor_id, project_id, "membership_write")
        return list(
            self.session.scalars(
                select(ProjectInvitation)
                .where(ProjectInvitation.project_id == project_id)
                .order_by(ProjectInvitation.created_at.desc(), ProjectInvitation.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def inbox(self, user_id: str, limit: int, offset: int) -> list[ProjectInvitation]:
        return list(
            self.session.scalars(
                select(ProjectInvitation)
                .where(
                    ProjectInvitation.invitee_id == user_id,
                    ProjectInvitation.status == "pending",
                    ProjectInvitation.expires_at > datetime.now(UTC),
                )
                .order_by(ProjectInvitation.created_at.desc(), ProjectInvitation.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def decide_invitation(
        self, user_id: str, invitation_id: str, accept: bool
    ) -> ProjectInvitation:
        found = self.session.scalar(
            select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id, ProjectInvitation.invitee_id == user_id
            )
        )
        if found is None:
            raise missing()
        # Lock order is always project then invitation, matching administrative actions.
        project = self.session.scalar(
            select(Project).where(Project.id == found.project_id).with_for_update()
        )
        if project is None or project.lifecycle_status != "active":
            raise missing()
        invite = self.invitation(project.id, invitation_id, lock=True)
        if invite.invitee_id != user_id or invite.status != "pending":
            raise conflict()
        if invite.expires_at <= datetime.now(UTC):
            invite.status = "expired"
            self.commit()
            raise ControlPlaneError(410, "expired", "Invitation has expired")
        invitee = self.session.scalar(
            select(User).where(User.id == user_id, User.is_active.is_(True))
        )
        inviter = self.session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == invite.inviter_id,
                ProjectMembership.status == "active",
            )
        )
        if (
            invitee is None
            or inviter is None
            or invite.role not in ASSIGNABLE.get(inviter.role, ())
            or ((inviter.role == "owner") != (project.owner_id == inviter.user_id))
        ):
            invite.status = "revoked"
            self.commit()
            raise conflict()
        if accept:
            member = self.session.scalar(
                select(ProjectMembership)
                .where(
                    ProjectMembership.project_id == project.id, ProjectMembership.user_id == user_id
                )
                .with_for_update()
            )
            if member and member.status == "active":
                raise conflict()
            if member:
                member.role, member.status, member.revoked_at = invite.role, "active", None
            else:
                self.session.add(
                    ProjectMembership(project_id=project.id, user_id=user_id, role=invite.role)
                )
            invite.status = "accepted"
        else:
            invite.status = "declined"
        self.commit()
        return invite

    def revoke_invitation(
        self, actor_id: str, project_id: str, invitation_id: str
    ) -> ProjectInvitation:
        self.access(actor_id, project_id, "membership_write", lock=True, require_active=False)
        invitation = self.invitation(project_id, invitation_id, lock=True)
        if invitation.status != "pending":
            raise conflict()
        invitation.status = "revoked"
        self.commit()
        return invitation

    def environment(
        self, project_id: str, environment_id: str, *, lock: bool = False
    ) -> Environment:
        query = select(Environment).where(
            Environment.project_id == project_id, Environment.id == environment_id
        )
        if lock:
            query = query.with_for_update()
        environment = self.session.scalar(query)
        if environment is None:
            raise missing()
        return environment

    def environments(
        self, actor_id: str, project_id: str, limit: int, offset: int
    ) -> list[Environment]:
        self.access(actor_id, project_id)
        return list(
            self.session.scalars(
                select(Environment)
                .where(Environment.project_id == project_id)
                .order_by(Environment.created_at, Environment.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def create_environment(self, actor_id: str, project_id: str, values: dict) -> Environment:
        self.access(actor_id, project_id, "environment_write", lock=True)
        environment = Environment(project_id=project_id, **values)
        self.session.add(environment)
        self.commit()
        return environment

    def update_environment(
        self, actor_id: str, project_id: str, environment_id: str, changes: dict
    ) -> Environment:
        self.access(actor_id, project_id, "environment_write", lock=True)
        environment = self.environment(project_id, environment_id, lock=True)
        if environment.lifecycle_status != "active":
            raise ControlPlaneError(409, "archived", "Archived resources cannot be modified")
        for key, value in changes.items():
            setattr(environment, key, value)
        self.commit()
        return environment

    def archive_environment(
        self, actor_id: str, project_id: str, environment_id: str
    ) -> Environment:
        self.access(actor_id, project_id, "environment_write", lock=True)
        environment = self.environment(project_id, environment_id, lock=True)
        if environment.lifecycle_status != "archived":
            environment.lifecycle_status = "archived"
            self.commit()
        return environment
