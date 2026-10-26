"""Pinned tools shared by protected fixture verification and the build executor."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

RAILPACK_VERSION = "0.43.0"
RAILPACK_SHA256 = "248a8f60f36854aabed6124113631078a802de3461660855fc4de9c26065c1fb"
FRONTEND = (
    "ghcr.io/railwayapp/railpack-frontend@"
    "sha256:355ef61fae6f2551103cd8b10c710cb07167dd353d561f15c69b8d7ac1c676cc"
)
FIXTURES = {"python": ["--start-cmd", "python main.py"], "node": [], "go": []}
BUILDKIT_VERSION = "v0.34.0"
# Hashes of audited fixture trees, including relative names and file contents.
FIXTURE_SHA256 = {
    "go": "9a5758a9e2c9899fda48295b50782d10d75f31d49f00fa5586e934c85c65d1a0",
    "node": "6418b33a80ec49a53c2c93d3ca7d342a9396f61918d01fc591818ac2fb1cdd56",
    "python": "f51db1d534fb49dccd7457a1e16068849ee1ed1f5b65a4bd5affc8b7bcdc9171",
}


def fixture_digest(context: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(context.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Fixture symlinks are forbidden")
        if path.is_file():
            digest.update(path.relative_to(context).as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def run(argv: list[str], *, timeout: int = 1200) -> str:
    # Output stays off the process heap and is never emitted without redaction.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            argv, stdout=output, stderr=subprocess.STDOUT, timeout=timeout, check=False
        )
        size = output.tell()
        output.seek(max(0, size - 4000) if result.returncode else 0)
        data = output.read(1024 * 1024).decode(errors="replace")
    if result.returncode:
        excerpt = re.sub(r"(?i)(password|token|secret)\s*[=:]\s*\S+", r"\1=[REDACTED]", data)
        raise RuntimeError(f"Tool failed with exit {result.returncode}: {excerpt}")
    if size > 1024 * 1024:
        raise RuntimeError("Tool output exceeded its limit")
    return data


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


def validate_trusted_source(root: Path, source_commit: str, fixture: str) -> Path:
    protected_main = (
        os.environ.get("GITHUB_EVENT_NAME") == "push"
        and os.environ.get("GITHUB_SHA") == source_commit
    )
    protected_promotion = (
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("LAVA_PROMOTED_SOURCE_SHA") == source_commit
        and os.environ.get("GITHUB_SHA") != source_commit
    )
    if not (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and os.environ.get("GITHUB_REPOSITORY") == "ralphdeeney/lava"
        and (protected_main or protected_promotion)
    ):
        raise PermissionError("Real fixture builds require a protected trusted workflow")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Invalid fixture source commit")
    actual = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != source_commit or fixture not in FIXTURES:
        raise ValueError("Unapproved fixture source identity")
    context = root / "build-fixtures" / fixture
    if (
        context.is_symlink()
        or context.parent.is_symlink()
        or fixture_digest(context) != FIXTURE_SHA256[fixture]
    ):
        raise ValueError("Fixture integrity verification failed")
    if shutil.disk_usage(root).free < 4 * 1024**3:
        raise RuntimeError("At least 4 GiB free disk is required")
    return context


def build_fixture(root: Path, source_commit: str, fixture: str, output: Path) -> dict:
    """Produce an OCI archive and verify its content-addressed blobs.

    This runs only inside the separate trusted executor, never in the API/worker.
    Losing the Docker client does not prove daemon-side termination; cancellation
    remains UNKNOWN until a trusted reconciliation can establish that outcome.
    """
    import tarfile

    context = validate_trusted_source(root, source_commit, fixture)
    builder = run(["docker", "context", "show"]).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", builder):
        raise ValueError("Invalid builder identity")
    info = run(["docker", "buildx", "inspect", "--builder", builder, "--bootstrap"])
    version = re.search(r"BuildKit(?: version)?:\s*(v[0-9]+\.[0-9]+\.[0-9]+)", info)
    if version is None or version.group(1) != BUILDKIT_VERSION:
        raise ValueError("Unapproved BuildKit version")
    with tempfile.TemporaryDirectory(prefix="lava-build-", dir=output.parent) as scratch:
        directory = Path(scratch)
        railpack = install_railpack(directory)
        plan, detection = directory / "plan.json", directory / "info.json"
        run(
            [
                str(railpack),
                "prepare",
                str(context),
                "--plan-out",
                str(plan),
                "--info-out",
                str(detection),
                "--hide-pretty-plan",
                *FIXTURES[fixture],
            ],
            timeout=300,
        )
        if not json.loads(detection.read_text()).get("success"):
            raise ValueError("Railpack fixture detection failed")
        metadata, archive = directory / "metadata.json", directory / "image.tar"
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
                "--output",
                f"type=oci,dest={archive}",
                "-f",
                str(plan),
                str(context),
            ],
            timeout=1200,
        )
        digest = json.loads(metadata.read_text()).get("containerimage.digest", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("Invalid OCI image digest")
        with tarfile.open(archive) as image:
            index = json.load(image.extractfile("index.json"))
            if digest not in {entry["digest"] for entry in index["manifests"]}:
                raise ValueError("OCI manifest digest mismatch")
            for member in image:
                if member.isfile() and member.name.startswith("blobs/sha256/"):
                    stream = image.extractfile(member)
                    if (
                        hashlib.file_digest(stream, "sha256").hexdigest()
                        != member.name.rsplit("/", 1)[1]
                    ):
                        raise ValueError("OCI blob digest mismatch")
        result = {
            "image_digest": digest,
            "source_commit": source_commit,
            "railpack_version": RAILPACK_VERSION,
            "buildkit_version": BUILDKIT_VERSION,
        }
        output.write_text(json.dumps(result))
        return result
