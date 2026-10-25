"""Transactional metadata use cases, independent of HTTP and container infrastructure."""

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lava.application.tenancy import Tenancy
from lava.db.base import Project, ProjectInvitation, ProjectMembership, Service
from lava.domain.control_plane import ControlPlaneError
from lava.persistence.control_plane import ControlPlaneRepository


class ControlPlane:
    def __init__(self, session: Session):
        self.session = session
        self.repository = ControlPlaneRepository(session)
        self.tenancy = Tenancy(session)

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise ControlPlaneError(
                409, "conflict", "Resource conflicts with existing state"
            ) from None

    @staticmethod
    def _active(project: Project) -> None:
        if project.lifecycle_status != "active":
            raise ControlPlaneError(409, "archived", "Archived resources cannot be modified")

    def create_project(self, owner_id: str, name: str, description: str) -> Project:
        project = Project(owner_id=owner_id, name=name, description=description)
        self.session.add(project)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            raise ControlPlaneError(
                409, "conflict", "Resource conflicts with existing state"
            ) from None
        self.session.add(ProjectMembership(project_id=project.id, user_id=owner_id, role="owner"))
        self._commit()
        return project

    def update_project(self, owner_id: str, project_id: str, changes: dict) -> Project:
        project, _ = self.tenancy.access(owner_id, project_id, "project_write", lock=True)
        self._active(project)
        for key, value in changes.items():
            setattr(project, key, value)
        self._commit()
        return project

    def archive_project(self, owner_id: str, project_id: str) -> Project:
        project, _ = self.tenancy.access(
            owner_id, project_id, "project_write", lock=True, require_active=False
        )
        if project.lifecycle_status == "active":
            project.lifecycle_status = "archived"
            self.session.execute(
                update(Service)
                .where(Service.project_id == project.id, Service.desired_state != "archived")
                .values(desired_state="archived")
            )
            self.session.execute(
                update(ProjectInvitation)
                .where(
                    ProjectInvitation.project_id == project.id,
                    ProjectInvitation.status == "pending",
                )
                .values(status="revoked")
            )
            self._commit()
        return project

    def create_service(self, owner_id: str, project_id: str, values: dict) -> Service:
        project, _ = self.tenancy.access(owner_id, project_id, "service_write", lock=True)
        self._active(project)
        environment_id = values.get("environment_id")
        if environment_id is not None:
            environment = self.tenancy.environment(project.id, str(environment_id))
            if environment.lifecycle_status != "active":
                raise ControlPlaneError(409, "archived", "Archived resources cannot be modified")
            values["environment_id"] = environment.id
        service = Service(project_id=project.id, **values)
        self.session.add(service)
        self._commit()
        return service

    def update_service(
        self, owner_id: str, project_id: str, service_id: str, changes: dict
    ) -> Service:
        project, _ = self.tenancy.access(owner_id, project_id, "service_write", lock=True)
        service = self.repository.service(project.id, service_id, lock=True)
        self._active(project)
        if service.desired_state == "archived":
            raise ControlPlaneError(409, "archived", "Archived resources cannot be modified")
        if "environment_id" in changes and changes["environment_id"] is not None:
            environment = self.tenancy.environment(project.id, str(changes["environment_id"]))
            if environment.lifecycle_status != "active":
                raise ControlPlaneError(409, "archived", "Archived resources cannot be modified")
            changes["environment_id"] = environment.id
        if service.environment_id:
            current_environment = self.tenancy.environment(project.id, service.environment_id)
            if (
                current_environment.lifecycle_status != "active"
                and changes.get("environment_id", service.environment_id) == service.environment_id
            ):
                raise ControlPlaneError(409, "archived", "Archived resources cannot be modified")
        if any(
            key in changes
            for key in (
                "resources",
                "environment_id",
                "build_method",
                "start_command",
                "deployment_branch",
                "desired_replicas",
            )
        ):
            service.config_revision += 1
        for key, value in changes.items():
            if key == "resources":
                # PATCH only changes supplied resource keys, including an empty no-op.
                value = {**service.resources, **value}
            setattr(service, key, value)
        self._commit()
        return service

    def archive_service(self, owner_id: str, project_id: str, service_id: str) -> Service:
        project, _ = self.tenancy.access(owner_id, project_id, "service_write", lock=True)
        service = self.repository.service(project.id, service_id, lock=True)
        if service.desired_state != "archived":
            service.desired_state = "archived"
            self._commit()
        return service
