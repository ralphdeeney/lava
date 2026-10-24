"""Disposable Phase 00 integration gate. Never changes daemon configuration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def redact(value: str, credentials: list[str]) -> str:
    for credential in credentials:
        if credential:
            value = value.replace(credential, "[REDACTED]")
    value = re.sub(r"(https?://)[^/\s@]+:[^/\s@]+@", r"\1[REDACTED]@", value)
    value = re.sub(
        r"(?i)(postgres(?:ql)?(?:\+psycopg)?://)[^\s]+", r"\1[REDACTED]", value
    )
    return re.sub(
        r"(?i)((?:password|token|secret|authorization)\s*[=:]\s*)\S+",
        r"\1[REDACTED]",
        value,
    )


def database_storage_guard(data: Path, docker_root: Path, allow_root: bool) -> None:
    """Inspect mounts only: never edit daemon.json or move Docker data."""
    if allow_root:
        print("Explicit ephemeral-run override: Docker storage location is unchanged.")
        return
    # Refuse accidental use of an unmounted /data directory on the VM root disk.
    if not data.is_mount() or data.stat().st_dev == Path("/").stat().st_dev:
        raise RuntimeError(
            "Data directory must be a separate mounted filesystem (default /data)."
        )
    if docker_root.stat().st_dev != data.stat().st_dev:
        raise RuntimeError(
            "Docker data-root is not on the selected data filesystem. No storage changes made. "
            "Inspect storage with the VM operator and obtain explicit authorization before migration."
        )


def assert_safe_config(config: dict) -> None:
    services = config["services"]
    if services["db"].get("ports"):
        raise RuntimeError("PostgreSQL must not publish host ports")
    for name, service in services.items():
        if service.get("privileged") or service.get("network_mode") == "host":
            raise RuntimeError(f"Unsafe privilege/network mode: {name}")
        for mount in service.get("volumes", []):
            source = str(mount.get("source", ""))
            target = str(mount.get("target", ""))
            if "docker.sock" in source or "docker.sock" in target:
                raise RuntimeError(f"Docker socket mount forbidden: {name}")
    for name in ("api", "web"):
        if not services[name].get("ports") or any(
            port.get("host_ip") != "127.0.0.1" for port in services[name]["ports"]
        ):
            raise RuntimeError(f"HTTP port must bind loopback: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("/data"))
    parser.add_argument(
        "--allow-root-storage",
        action="store_true",
        help="Explicit override for ephemeral CI/cloud only; not recommended on InstaBox",
    )
    parser.add_argument(
        "--cloud", action="store_true", help="Use the managed-cloud CA build override"
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)

    def interrupted(signum, frame):
        raise RuntimeError(f"Interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    for tool in ("git", "docker", "node", "uv"):
        if not shutil.which(tool):
            raise RuntimeError(f"Missing prerequisite: {tool}")
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Python 3.13 is required")
    if not os.access(ROOT, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError("Checkout must be readable and writable by the current user")
    data = args.data_dir.resolve()
    if not data.is_dir() or not os.access(data, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError(
            "Data directory must exist and be writable; script will not create/mount a disk"
        )
    output = data / "lava-verification"
    output.mkdir(mode=0o700, exist_ok=True)
    if output.is_symlink() or output.stat().st_uid != os.getuid():
        raise RuntimeError(
            "Verification directory must be owned by this user and not a symlink"
        )
    output.chmod(0o700)
    run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=output))
    credentials: list[str] = []
    env = os.environ.copy()
    # Never inherit another project's compose selection or database credentials.
    for name in list(env):
        if name.startswith("COMPOSE_") or name in (
            "POSTGRES_USER",
            "POSTGRES_DB",
            "POSTGRES_PASSWORD",
            "LAVA_DATABASE_URL",
        ):
            env.pop(name)
    env["COMPOSE_PARALLEL_LIMIT"] = "1"
    env["BUILDX_CONFIG"] = str(output / "buildx")
    Path(env["BUILDX_CONFIG"]).mkdir(exist_ok=True)

    def command(
        argv: list[str], *, timeout: int = 120, check: bool = True
    ) -> subprocess.CompletedProcess:
        result = subprocess.run(
            argv,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        # Raw subprocess output stays in memory only. Log redacted, bounded excerpts.
        with (run_dir / "commands.log").open("a") as log:
            log.write(redact(result.stdout[-32768:], credentials) + "\n")
        if check and result.returncode:
            raise RuntimeError(
                f"Command failed ({result.returncode}): {argv[0]} {argv[1] if len(argv) > 1 else ''}"
            )
        return result

    node = command(["node", "--version"]).stdout.strip()
    if int(node.lstrip("v").split(".")[0]) < 22:
        raise RuntimeError("Node 22 or newer is required")
    uv = command(["uv", "--version"]).stdout.strip()
    if not uv.startswith("uv 0.12.23 "):
        raise RuntimeError(
            "uv 0.12.23 is required; install it before running verification"
        )
    compose_version = command(
        ["docker", "compose", "version", "--short"]
    ).stdout.strip()
    if tuple(int(x) for x in compose_version.lstrip("v").split(".")[:3]) < (2, 24, 4):
        raise RuntimeError("Compose >=2.24.4 is required for safe port overrides")
    info = json.loads(
        command(
            [
                "docker",
                "info",
                "--format",
                '{"ServerVersion":{{json .ServerVersion}},"DockerRootDir":{{json .DockerRootDir}}}',
            ]
        ).stdout
    )
    docker_root = Path(info["DockerRootDir"])
    if not args.allow_root_storage:
        # The filesystem check only makes sense for a local daemon.
        context = command(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]
        )
        if env.get("DOCKER_HOST", context.stdout.strip()) not in (
            "unix:///var/run/docker.sock",
            "unix:///run/docker.sock",
        ):
            raise RuntimeError("Storage inspection requires the local VM Docker daemon")
    print(
        f"Observed tools: Python {sys.version.split()[0]}, Node {node}, {uv}, "
        f"Docker {info['ServerVersion']}, Compose {compose_version}"
    )
    print(f"Observed Docker data-root: {docker_root}; data directory: {data}")
    database_storage_guard(data, docker_root, args.allow_root_storage)
    free = shutil.disk_usage(data).free
    if free < 4 * 1024**3:
        raise RuntimeError("At least 4 GiB free on the selected data disk is required")
    print(f"Data disk free space: {free // 1024**2} MiB; diagnostics: {run_dir}")
    if args.preflight_only:
        print(
            "Preflight passed; no containers created. This is not a full integration result."
        )
        return 0

    project = "lava-verify-" + secrets.token_hex(6)
    password = secrets.token_hex(24)
    credentials.append(password)
    envfile = run_dir / "compose.env"
    envfile.write_text(
        f"POSTGRES_USER=lava\nPOSTGRES_DB=lava_verification_test\n"
        f"POSTGRES_PASSWORD={password}\nLAVA_ENVIRONMENT=test\n"
    )
    override = run_dir / "ports.yaml"
    override.write_text(
        'services:\n  api:\n    ports: !override\n      - "127.0.0.1::8000"\n'
        '  web:\n    ports: !override\n      - "127.0.0.1::3000"\n'
    )
    compose = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(envfile),
        "-f",
        str(ROOT / "compose.yaml"),
    ]
    if args.cloud:
        compose += ["-f", str(ROOT / "compose.cloud.yaml")]
    compose += ["-f", str(override)]
    started = False
    status = 1
    try:
        existing = command(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ]
        ).stdout.strip()
        volumes = command(
            [
                "docker",
                "volume",
                "ls",
                "-q",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ]
        ).stdout.strip()
        if existing or volumes:
            raise RuntimeError("Refusing to reuse an existing verification project")
        config = json.loads(command(compose + ["config", "--format", "json"]).stdout)
        assert_safe_config(config)
        # Do not retain rendered config: it contains the password.
        (run_dir / "commands.log").write_text("")
        started = True
        command(
            compose + ["up", "--build", "--wait", "--wait-timeout", "180"], timeout=900
        )
        for service, container_port in (("api", "8000"), ("web", "3000")):
            address = command(
                compose + ["port", service, container_port]
            ).stdout.strip()
            if not re.fullmatch(r"127\.0\.0\.1:\d+", address):
                raise RuntimeError("Unexpected published HTTP address")
            targets = (
                [("/health", "ok"), ("/ready", "ready")]
                if service == "api"
                else [("/", None)]
            )
            for path, expected in targets:
                with urllib.request.urlopen(
                    f"http://{address}{path}", timeout=10
                ) as response:
                    body = response.read()
                    if response.status != 200:
                        raise RuntimeError(f"HTTP check failed: {service}")
                    if expected and json.loads(body) != {"status": expected}:
                        raise RuntimeError(f"Unexpected {path} response")
                    if expected is None and b"A foundation for shipping." not in body:
                        raise RuntimeError("Frontend functional check failed")
        command(
            compose
            + [
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "lava",
                "-d",
                "lava_verification_test",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "SELECT 1;",
            ]
        )
        # Reapplying head must be safe; schema drift is independently checked.
        command(compose + ["exec", "-T", "api", "alembic", "upgrade", "head"])
        command(compose + ["exec", "-T", "api", "alembic", "upgrade", "head"])
        command(compose + ["exec", "-T", "api", "alembic", "check"])
        for service in ("api", "web"):
            uid = command(compose + ["exec", "-T", service, "id", "-u"]).stdout.strip()
            if uid == "0":
                raise RuntimeError(f"Public service runs as root: {service}")
        print(
            "PASS: Compose startup, HTTP, PostgreSQL, repeat migrations, schema and non-root checks"
        )
        status = 0
    except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        print(redact(str(exc), credentials), file=sys.stderr)
        if started:
            for argv in (["ps", "--all"], ["logs", "--no-color", "--tail", "80"]):
                try:
                    command(compose + argv, timeout=30, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass
    finally:
        if started:
            try:
                # Unique random project only: never prune global resources or use --remove-orphans.
                command(
                    compose
                    + ["down", "--volumes", "--rmi", "local", "--timeout", "15"],
                    timeout=90,
                )
                leftovers = command(
                    [
                        "docker",
                        "ps",
                        "-aq",
                        "--filter",
                        f"label=com.docker.compose.project={project}",
                    ]
                ).stdout.strip()
                volumes = command(
                    [
                        "docker",
                        "volume",
                        "ls",
                        "-q",
                        "--filter",
                        f"label=com.docker.compose.project={project}",
                    ]
                ).stdout.strip()
                if leftovers or volumes:
                    raise RuntimeError(
                        "Verification resources remain; inspect the unique project"
                    )
                print(
                    "PASS: disposable project teardown; unrelated resources untouched"
                )
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                print(redact(str(exc), credentials), file=sys.stderr)
                status = 1
        envfile.unlink(missing_ok=True)
        override.unlink(missing_ok=True)
        # Bound the retained diagnostic file across all command invocations.
        log = run_dir / "commands.log"
        if log.exists():
            log.write_bytes(
                redact(log.read_text(), credentials)
                .encode()[-65536:]
                .decode(errors="ignore")
                .encode()
            )
        print(f"Bounded, redacted diagnostics: {run_dir}")
    return status


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        # Preflight errors do not include command output or process environments.
        print(f"Preflight failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
