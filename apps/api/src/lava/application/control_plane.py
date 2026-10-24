"""Transactional metadata use cases, independent of HTTP and container infrastructure."""

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lava.db.base import Project, Service
from lava.domain.control_plane import ControlPlaneError
from lava.persistence.control_plane import ControlPlaneRepository


class ControlPlane:
    def __init__(self, session: Session):
        self.session = session
        self.repository = ControlPlaneRepository(session)

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
        self._commit()
        return project

    def update_project(self, owner_id: str, project_id: str, changes: dict) -> Project:
        project = self.repository.project(owner_id, project_id, lock=True)
        self._active(project)
        for key, value in changes.items():
            setattr(project, key, value)
        self._commit()
        return project

    def archive_project(self, owner_id: str, project_id: str) -> Project:
        project = self.repository.project(owner_id, project_id, lock=True)
        if project.lifecycle_status == "active":
            project.lifecycle_status = "archived"
            self.session.execute(
                update(Service)
                .where(Service.project_id == project.id, Service.desired_state != "archived")
                .values(desired_state="archived")
            )
            self._commit()
        return project

    def create_service(self, owner_id: str, project_id: str, values: dict) -> Service:
        project = self.repository.project(owner_id, project_id, lock=True)
        self._active(project)
        service = Service(project_id=project.id, **values)
        self.session.add(service)
        self._commit()
        return service

    def update_service(
        self, owner_id: str, project_id: str, service_id: str, changes: dict
    ) -> Service:
        project = self.repository.project(owner_id, project_id, lock=True)
        service = self.repository.service(project.id, service_id, lock=True)
        self._active(project)
        if service.desired_state == "archived":
            raise ControlPlaneError(409, "archived", "Archived resources cannot be modified")
        for key, value in changes.items():
            setattr(service, key, value)
        self._commit()
        return service

    def archive_service(self, owner_id: str, project_id: str, service_id: str) -> Service:
        project = self.repository.project(owner_id, project_id, lock=True)
        service = self.repository.service(project.id, service_id, lock=True)
        if service.desired_state != "archived":
            service.desired_state = "archived"
            self._commit()
        return service
