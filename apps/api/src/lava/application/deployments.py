"""Deployment metadata transactions; execution is deliberately out of scope."""

import re
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lava.application.tenancy import Tenancy
from lava.db.base import Deployment, DeploymentEvent, DeploymentJob, Environment, Service
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
    "queued": {"building", "failed", "cancelled"},
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
        values = dict(values)
        values["environment_id"] = str(values["environment_id"])
        if service.environment_id != values["environment_id"]:
            raise ControlPlaneError(409, "environment_conflict", "Service environment mismatch")
        if values["configuration_revision"] != service.config_revision:
            raise ControlPlaneError(409, "stale_configuration", "Service configuration changed")
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
                "image_digest",
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
                deployment_id=deployment.id,
                sequence=0,
                to_status="queued",
                message="Deployment queued",
            )
        )
        self.session.add(DeploymentJob(deployment_id=deployment.id))
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
        expected_version: int | None = None,
        message: str | None = None,
        failure_code: str | None = None,
        commit: bool = True,
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
        version = deployment.transition_version if expected_version is None else expected_version
        if version != deployment.transition_version:
            raise ControlPlaneError(409, "stale_transition", "Deployment transition is stale")
        sequence = self.session.scalar(
            select(func.coalesce(func.max(DeploymentEvent.sequence), -1) + 1).where(
                DeploymentEvent.deployment_id == deployment.id
            )
        )
        values = {
            "status": target,
            "transition_version": version + 1,
            "updated_at": now,
        }
        if target in {"building", "deploying", "verifying"} and deployment.started_at is None:
            values["started_at"] = now
        if target in TERMINAL:
            values["finished_at"] = now
        if target == "failed":
            values["failure_code"] = "deployment_failed"
            values["failure_message"] = "Deployment failed"
        result = self.session.execute(
            update(Deployment)
            .where(
                Deployment.id == deployment.id,
                Deployment.status == previous,
                Deployment.transition_version == version,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            self.session.rollback()
            raise ControlPlaneError(409, "stale_transition", "Deployment transition is stale")
        self.session.add(
            DeploymentEvent(
                deployment_id=deployment.id,
                sequence=sequence,
                from_status=previous,
                to_status=target,
                message="Deployment state changed",
            )
        )
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return deployment
