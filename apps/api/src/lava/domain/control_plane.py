"""Control-plane metadata states; no infrastructure side effects."""

from enum import StrEnum


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ServiceType(StrEnum):
    WEB = "web"
    API = "api"
    WORKER = "worker"
    DATABASE = "database"


class DesiredState(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    ARCHIVED = "archived"


class ControlPlaneError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
