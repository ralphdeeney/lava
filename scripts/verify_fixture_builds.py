"""Build audited fixtures with pinned Railpack and the runner's Docker BuildKit.

Run only on disposable CI runners without production or InstaBox credentials.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lava.application.build_artifacts import record_build_artifact
from lava.db.base import (
    Deployment,
    DeploymentEvent,
    DeploymentJob,
    Environment,
    Project,
    Service,
    User,
)
from lava.worker import DeploymentWorker

ROOT = Path(__file__).resolve().parents[1]
RAILPACK_VERSION = "0.43.0"
RAILPACK_SHA256 = "248a8f60f36854aabed6124113631078a802de3461660855fc4de9c26065c1fb"
FRONTEND = (
    "ghcr.io/railwayapp/railpack-frontend@"
    "sha256:355ef61fae6f2551103cd8b10c710cb07167dd353d561f15c69b8d7ac1c676cc"
)
FIXTURES = {"python": ["--start-cmd", "python main.py"], "node": [], "go": []}


def run(argv: list[str], *, timeout: int = 1200) -> str:
    result = subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        excerpt = (result.stdout + result.stderr)[-4000:]
        excerpt = re.sub(
            r"(?i)(password|token|secret)\s*[=:]\s*\S+", r"\1=[REDACTED]", excerpt
        )
        raise RuntimeError(f"{argv[0]} failed with exit {result.returncode}: {excerpt}")
    return result.stdout


def install_railpack(directory: Path) -> Path:
    filename = f"railpack-v{RAILPACK_VERSION}-x86_64-unknown-linux-musl.tar.gz"
    url = f"https://github.com/railwayapp/railpack/releases/download/v{RAILPACK_VERSION}/{filename}"
    with urlopen(url, timeout=60) as response:
        archive = response.read(80 * 1024 * 1024)
    if hashlib.sha256(archive).hexdigest() != RAILPACK_SHA256:
        raise RuntimeError("Railpack archive checksum mismatch")
    archive_path = directory / filename
    archive_path.write_bytes(archive)
    with tarfile.open(archive_path) as contents:
        binary = contents.extractfile("railpack")
        if binary is None:
            raise RuntimeError("Railpack binary missing")
        path = directory / "railpack"
        path.write_bytes(binary.read())
    path.chmod(0o700)
    if RAILPACK_VERSION not in run([str(path), "--version"]):
        raise RuntimeError("Unexpected Railpack version")
    return path


def create_fixture_job(engine, name: str, source_commit: str) -> tuple[str, str, str]:
    with Session(engine) as session:
        user = User(name=f"fixture-builder-{name}-{uuid4().hex[:8]}")
        session.add(user)
        session.flush()
        project = Project(name=f"fixture-{name}-{uuid4().hex[:8]}", owner_id=user.id)
        session.add(project)
        session.flush()
        environment = Environment(project_id=project.id, name="build", slug="build")
        session.add(environment)
        session.flush()
        service = Service(
            project_id=project.id,
            environment_id=environment.id,
            name=name,
            service_type="web",
            resources={"cpu": 1, "memory_mb": 512},
        )
        session.add(service)
        session.flush()
        deployment = Deployment(
            project_id=project.id,
            environment_id=environment.id,
            service_id=service.id,
            source_type="git",
            repository_url="https://github.com/ralphdeeney/lava",
            source_commit_sha=source_commit,
            source_branch="fixture",
            configuration_revision=1,
            idempotency_key=f"fixture-{name}-{source_commit}",
            created_by=user.id,
        )
        session.add(deployment)
        session.flush()
        session.add_all(
            [
                DeploymentEvent(
                    deployment_id=deployment.id, sequence=0, to_status="queued"
                ),
                DeploymentJob(deployment_id=deployment.id),
            ]
        )
        session.commit()
        claimed = DeploymentWorker(
            session, "trusted-fixture-builder", lease_seconds=1800
        ).claim()
        if claimed is None:
            raise RuntimeError("Fixture job could not be claimed")
        job, token = claimed
        return deployment.id, job.id, token


def main() -> None:
    if os.environ.get("LAVA_TRUSTED_FIXTURE_CI") != "1":
        raise RuntimeError("Fixture builds require an explicitly isolated CI runner")
    if shutil.disk_usage(ROOT).free < 4 * 1024**3:
        raise RuntimeError("At least 4 GiB free disk is required")
    source_commit = run(["git", "rev-parse", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RuntimeError("Invalid source commit")
    evidence = []
    database_url = os.environ.get("LAVA_DATABASE_URL")
    if not database_url:
        raise RuntimeError("Disposable provenance database is required")
    engine = create_engine(database_url)
    builder = run(["docker", "context", "show"]).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", builder):
        raise RuntimeError("Unsafe Docker context name")
    builder_info = run(
        ["docker", "buildx", "inspect", "--builder", builder, "--bootstrap"]
    )
    buildkit_match = re.search(r"BuildKit:\s*(v[0-9]+\.[0-9]+\.[0-9]+)", builder_info)
    if buildkit_match is None:
        raise RuntimeError("BuildKit version is unavailable")
    buildkit_version = buildkit_match.group(1)
    with tempfile.TemporaryDirectory(prefix="lava-fixture-build-") as scratch:
        temporary = Path(scratch)
        railpack = install_railpack(temporary)
        for name, options in FIXTURES.items():
            deployment_id, job_id, token = create_fixture_job(
                engine, name, source_commit
            )
            context = ROOT / "build-fixtures" / name
            plan = temporary / f"{name}-plan.json"
            info = temporary / f"{name}-info.json"
            run(
                [
                    str(railpack),
                    "prepare",
                    str(context),
                    "--plan-out",
                    str(plan),
                    "--info-out",
                    str(info),
                    "--hide-pretty-plan",
                    *options,
                ],
                timeout=300,
            )
            if not json.loads(info.read_text()).get("success"):
                raise RuntimeError(f"Railpack could not prepare {name}")
            tag = f"lava-fixture-{name}:{source_commit[:12]}"
            metadata = temporary / f"{name}-metadata.json"
            try:
                run(
                    [
                        "docker",
                        "buildx",
                        "build",
                        "--builder",
                        builder,
                        "--no-cache",
                        "--progress",
                        "plain",
                        "--build-arg",
                        f"BUILDKIT_SYNTAX={FRONTEND}",
                        "--metadata-file",
                        str(metadata),
                        "--load",
                        "--tag",
                        tag,
                        "-f",
                        str(plan),
                        str(context),
                    ],
                    timeout=1200,
                )
                result = json.loads(metadata.read_text())
                digest = result.get("containerimage.digest", "")
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                    raise RuntimeError(f"No OCI digest for {name}")
                run(["docker", "image", "inspect", tag])
                with Session(engine) as session:
                    artifact = record_build_artifact(
                        session,
                        job_id=job_id,
                        lease_owner="trusted-fixture-builder",
                        lease_token=token,
                        image_digest=digest,
                        railpack_version=RAILPACK_VERSION,
                        buildkit_version=buildkit_version,
                    )
                    if (
                        artifact.deployment_id != deployment_id
                        or artifact.image_digest != digest
                    ):
                        raise RuntimeError("Persisted build provenance mismatch")
                evidence.append(
                    {
                        "fixture": name,
                        "source_commit": source_commit,
                        "railpack_version": RAILPACK_VERSION,
                        "buildkit_version": buildkit_version,
                        "frontend": FRONTEND,
                        "image_digest": digest,
                        "status": "built",
                    }
                )
                print(
                    f"::notice file=scripts/verify_fixture_builds.py::fixture={name} digest={digest} commit={source_commit}",
                    flush=True,
                )
            finally:
                subprocess.run(
                    ["docker", "image", "rm", "--force", tag],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
    output = ROOT / "test-results" / "fixture-builds.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        message = re.sub(
            r"(?i)(password|token|secret)\s*[=:]\s*\S+", r"\1=[REDACTED]", str(error)
        )
        message = message[-3000:].replace("\n", "%0A")
        print(f"::error file=scripts/verify_fixture_builds.py::{message}", flush=True)
        raise SystemExit(1) from None
