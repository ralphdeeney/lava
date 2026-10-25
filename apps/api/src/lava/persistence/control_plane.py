"""Explicit ownership-scoped persistence queries."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from lava.db.base import Project, Service
from lava.domain.control_plane import ControlPlaneError


class ControlPlaneRepository:
    def __init__(self, session: Session):
        self.session = session

    def project(self, owner_id: str, project_id: str, *, lock: bool = False) -> Project:
        query = select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
        if lock:
            query = query.with_for_update()
        project = self.session.scalar(query)
        if project is None:
            raise ControlPlaneError(404, "not_found", "Resource not found")
        return project

    def projects(self, owner_id: str, limit: int, offset: int) -> list[Project]:
        return list(
            self.session.scalars(
                select(Project)
                .where(Project.owner_id == owner_id)
                .order_by(Project.created_at, Project.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def service(self, project_id: str, service_id: str, *, lock: bool = False) -> Service:
        query = select(Service).where(Service.id == service_id, Service.project_id == project_id)
        if lock:
            query = query.with_for_update()
        service = self.session.scalar(query)
        if service is None:
            raise ControlPlaneError(404, "not_found", "Resource not found")
        return service

    def services(self, project_id: str, limit: int, offset: int) -> list[Service]:
        return list(
            self.session.scalars(
                select(Service)
                .where(Service.project_id == project_id)
                .order_by(Service.created_at, Service.id)
                .limit(limit)
                .offset(offset)
            )
        )
