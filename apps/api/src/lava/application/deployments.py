"""Deployment metadata transactions; execution is deliberately out of scope."""

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lava.application.tenancy import Tenancy
from lava.db.base import Deployment, DeploymentEvent, Environment, Service
from lava.domain.control_plane import ControlPlaneError

STATUSES = {
    "queued",
    "building",
    "built",
    "deploying",
    "verifying",
    "active",
    "failed",
    "cancelled",
    "rolled_back",
}
TERMINAL = {"active", "failed", "cancelled", "rolled_back"}
TRANSITIONS = {
    "queued": {"building", "cancelled"},
    "building": {"built", "failed", "cancelled"},
    "built": {"deploying", "failed", "cancelled"},
    "deploying": {"verifying", "failed", "cancelled"},
    "verifying": {"active", "failed", "cancelled"},
}
SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


class DeploymentService:
    def __init__(self, session: Session):
        self.session = session
        self.tenancy = Tenancy(session)

    def create(self, actor_id: str, project_id: str, service_id: str, values: dict) -> Deployment:
        project, _ = self.tenancy.access(actor_id, project_id, "service_write", lock=True)
        service = self.session.scalar(
            select(Service).where(Service.id == service_id, Service.project_id == project.id)
        )
        if service is None or service.desired_state == "archived":
            raise ControlPlaneError(404, "not_found", "Resource not found")
        environment = self.session.scalar(
            select(Environment).where(
                Environment.id == values["environment_id"], Environment.project_id == project.id
            )
        )
        if environment is None or environment.lifecycle_status != "active":
            raise ControlPlaneError(404, "not_found", "Resource not found")
        if not SHA.fullmatch(values["source_commit_sha"]):
            raise ControlPlaneError(422, "invalid_source", "Invalid source commit")
        existing = self.session.scalar(
            select(Deployment).where(
                Deployment.project_id == project.id,
                Deployment.service_id == service.id,
                Deployment.idempotency_key == values["idempotency_key"],
            )
        )
        if existing:
            immutable = {
                "environment_id",
                "source_type",
                "repository_url",
                "source_commit_sha",
                "source_branch",
                "configuration_revision",
            }
            if any(getattr(existing, key) != values[key] for key in immutable):
                raise ControlPlaneError(
                    409, "conflict", "Idempotency key conflicts with existing deployment"
                )
            return existing
        deployment = Deployment(
            project_id=project.id,
            service_id=service.id,
            created_by=actor_id,
            status="queued",
            **values,
        )
        self.session.add(deployment)
        self.session.flush()
        self.session.add(
            DeploymentEvent(
                deployment_id=deployment.id, to_status="queued", message="Deployment queued"
            )
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise ControlPlaneError(
                409, "conflict", "Resource conflicts with existing state"
            ) from None
        return deployment

    def transition(
        self,
        deployment_id: str,
        target: str,
        *,
        message: str | None = None,
        failure_code: str | None = None,
    ) -> Deployment:
        if target not in STATUSES:
            raise ControlPlaneError(422, "invalid_status", "Invalid deployment status")
        deployment = self.session.scalar(
            select(Deployment).where(Deployment.id == deployment_id).with_for_update()
        )
        if deployment is None:
            raise ControlPlaneError(404, "not_found", "Resource not found")
        if target not in TRANSITIONS.get(deployment.status, set()):
            raise ControlPlaneError(
                409, "invalid_transition", "Deployment state transition is not allowed"
            )
        now = datetime.now(UTC)
        previous = deployment.status
        deployment.status = target
        deployment.updated_at = now
        if target in {"building", "deploying", "verifying"} and deployment.started_at is None:
            deployment.started_at = now
        if target in TERMINAL:
            deployment.finished_at = now
        if target == "failed":
            deployment.failure_code = (failure_code or "deployment_failed")[:80]
            deployment.failure_message = (message or "Deployment failed")[:500]
        self.session.add(
            DeploymentEvent(
                deployment_id=deployment.id,
                from_status=previous,
                to_status=target,
                message=(message or "")[:500] or None,
            )
        )
        self.session.commit()
        return deployment
