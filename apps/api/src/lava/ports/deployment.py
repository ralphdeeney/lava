"""Contracts only. Privileged adapters belong in a separate worker process."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BuildRequest:
    deployment_id: str
    source_path: str
    commit_sha: str


@dataclass(frozen=True)
class BuildResult:
    image_digest: str


@dataclass(frozen=True)
class RunRequest:
    deployment_id: str
    image_digest: str
    port: int


class BuildEngine(Protocol):
    async def build(self, request: BuildRequest) -> BuildResult: ...


class ContainerRuntime(Protocol):
    async def start(self, request: RunRequest) -> str: ...
    async def stop(self, container_id: str) -> None: ...


class DeploymentScheduler(Protocol):
    async def enqueue(self, deployment_id: str) -> None: ...


class Networking(Protocol):
    async def publish(self, deployment_id: str, hostname: str, target: str) -> None: ...
    async def withdraw(self, deployment_id: str) -> None: ...
