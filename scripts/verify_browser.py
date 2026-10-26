"""Run real desktop/mobile browser journeys against disposable PostgreSQL/API/SvelteKit."""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from lava.auth.accounts import provision_account
from lava.db.base import (
    ApiCredential,
    BrowserSession,
    Environment,
    PasswordAccount,
    Project,
    ProjectInvitation,
    ProjectMembership,
    Service,
    User,
)

# Keep script imports usable both from Python and as a repository entrypoint.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_fixture import require_test_database  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def wait_http(url: str, process: subprocess.Popen) -> None:
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError("Application process exited before readiness")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError("Application readiness timeout")


def public_failure_summary(report: dict, failures: list[dict]) -> list[dict]:
    """Expose only already-public test identities and a coarse error category."""
    categories = {}
    for entry in failures:
        diagnostic = str(entry.get("diagnostic", "")).casefold()
        category = (
            "timeout"
            if "timeout" in diagnostic
            else "assertion"
            if "expect" in diagnostic
            else "runtime"
        )
        categories[(entry.get("name"), entry.get("project"))] = category
    return [
        {
            "name": entry["name"],
            "project": entry["project"],
            "kind": categories.get((entry["name"], entry["project"]), "unknown"),
        }
        for entry in report.get("tests", [])
        if entry.get("status") == "failed"
    ]


def main() -> int:
    out = ROOT / "test-results/e2e"
    private = out / "harness-private"
    public = out / "public"
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    public.mkdir(parents=True, exist_ok=True)
    processes = []
    files = []
    users = []
    engine = None
    accounts = private / "accounts.json"
    code = 1
    try:
        url = require_test_database()
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "apps/api",
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        engine = create_engine(url)
        with Session(engine) as session:
            # Owner, developer, viewer, admin and an unrelated user are isolated
            # disposable identities; no shared or default account is required.
            for _ in range(5):
                name = "e2e-" + secrets.token_hex(12)
                password = secrets.token_urlsafe(32)
                user = provision_account(session, name, password)
                users.append({"id": user.id, "username": name, "password": password})
        descriptor = os.open(accounts, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"users": users}, stream)
        api_url, web_url = (
            f"http://127.0.0.1:{free_port()}",
            f"http://127.0.0.1:{free_port()}",
        )
        env = os.environ.copy()
        env.update(
            LAVA_ENVIRONMENT="test",
            LAVA_BROWSER_ORIGIN=web_url,
            LAVA_COOKIE_SECURE="false",
            LAVA_API_ORIGIN=api_url,
            ORIGIN=web_url,
            HOST="127.0.0.1",
            PORT=web_url.rsplit(":", 1)[1],
            LAVA_E2E_BASE_URL=web_url,
            LAVA_E2E_API_BASE_URL=api_url,
            LAVA_E2E_ACCOUNTS_FILE=str(accounts),
            LAVA_E2E_REPORT_DIR=str(public),
            LAVA_E2E_EXPIRE_HELPER=str(ROOT / "scripts/browser_fixture.py"),
            LAVA_E2E_PYTHON=sys.executable,
        )
        for name, argv, cwd in (
            (
                "api",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "lava.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    api_url.rsplit(":", 1)[1],
                    "--no-access-log",
                ],
                ROOT / "apps/api",
            ),
            ("web", ["node", "build"], ROOT / "apps/web"),
        ):
            descriptor = os.open(
                private / (name + ".log"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
            )
            log = os.fdopen(descriptor, "w")
            files.append(log)
            processes.append(
                subprocess.Popen(
                    argv,
                    cwd=cwd,
                    env=env,
                    stdout=log,
                    stderr=log,
                    stdin=subprocess.DEVNULL,
                )
            )
        wait_http(api_url + "/ready", processes[0])
        wait_http(web_url + "/login", processes[1])
        # Capture all raw diagnostics privately. Only the custom sanitized reporter is published.
        command = subprocess.run(
            ["pnpm", "exec", "playwright", "test"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        descriptor = os.open(
            private / "browser.log", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        with os.fdopen(descriptor, "w") as log:
            log.write(command.stdout + command.stderr)
        code = command.returncode
        if code and (public / "report.json").is_file():
            report = json.loads((public / "report.json").read_text())
            failure_path = out / "private/failures.json"
            failures = (
                json.loads(failure_path.read_text()) if failure_path.is_file() else []
            )
            print(
                json.dumps(
                    {
                        "browser_failed_journeys": public_failure_summary(
                            report, failures
                        )
                    }
                )
            )
        print(
            json.dumps(
                {
                    "browser_command_exit": code,
                    "report": "test-results/e2e/public/report.json",
                    "real_api": True,
                    "real_postgresql": True,
                    "trace_capture": False,
                }
            )
        )
    except Exception as error:
        print(
            json.dumps(
                {"browser_harness": "blocked", "error_type": type(error).__name__}
            )
        )
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in files:
            log.close()
        accounts.unlink(missing_ok=True)
        if engine is not None:
            try:
                ids = [user["id"] for user in users]
                with engine.begin() as connection:
                    projects = select(Project.id).where(Project.owner_id.in_(ids))
                    connection.execute(
                        delete(Service).where(Service.project_id.in_(projects))
                    )
                    connection.execute(
                        delete(ProjectInvitation).where(
                            ProjectInvitation.project_id.in_(projects)
                        )
                    )
                    connection.execute(
                        delete(ProjectMembership).where(
                            ProjectMembership.project_id.in_(projects)
                        )
                    )
                    connection.execute(
                        delete(Environment).where(Environment.project_id.in_(projects))
                    )
                    connection.execute(delete(Project).where(Project.owner_id.in_(ids)))
                    for model in (BrowserSession, PasswordAccount, ApiCredential):
                        connection.execute(delete(model).where(model.user_id.in_(ids)))
                    connection.execute(delete(User).where(User.id.in_(ids)))
            except Exception:
                code = 1
                print('{"browser_cleanup":"failed; scoped recovery required"}')
            finally:
                engine.dispose()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
