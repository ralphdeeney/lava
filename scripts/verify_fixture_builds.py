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


def main() -> None:
    if os.environ.get("LAVA_TRUSTED_FIXTURE_CI") != "1":
        raise RuntimeError("Fixture builds require an explicitly isolated CI runner")
    if shutil.disk_usage(ROOT).free < 4 * 1024**3:
        raise RuntimeError("At least 4 GiB free disk is required")
    source_commit = run(["git", "rev-parse", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RuntimeError("Invalid source commit")
    evidence = []
    with tempfile.TemporaryDirectory(prefix="lava-fixture-build-") as scratch:
        temporary = Path(scratch)
        railpack = install_railpack(temporary)
        for name, options in FIXTURES.items():
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
                        "default",
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
                evidence.append(
                    {
                        "fixture": name,
                        "source_commit": source_commit,
                        "railpack_version": RAILPACK_VERSION,
                        "frontend": FRONTEND,
                        "image_digest": digest,
                        "status": "built",
                    }
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
    main()
