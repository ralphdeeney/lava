"""Authenticated, bounded GitHub Actions -> InstaBox orchestration (API v1)."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from verify_instabox import redact

API = "https://api.instabox.sh"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("API redirects are refused to protect credentials")


class APIError(RuntimeError):
    def __init__(self, status: int, code: str):
        super().__init__(f"InstaBox HTTP {status}: {code}")
        self.status = status
        self.code = code


class Client:
    def __init__(self, key: str, machine: str):
        if not key or not re.fullmatch(r"[A-Za-z0-9_-]+", machine):
            raise RuntimeError("Required InstaBox secrets are missing or invalid")
        self.key = key
        self.machine = "/v1/machines/" + urllib.parse.quote(machine, safe="")
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        safe: bool = False,
        idempotency: str | None = None,
    ) -> dict:
        headers = {
            "X-API-Key": self.key,
            "Accept": "application/json",
            "User-Agent": "lava-phase00-ci/1",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        for attempt in range(4):
            request = urllib.request.Request(
                API + path,
                method=method,
                headers=headers,
                data=json.dumps(body).encode() if body is not None else None,
            )
            try:
                with self.opener.open(request, timeout=70) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                try:
                    error = json.load(exc).get("error", {})
                except (ValueError, OSError):
                    error = {}
                retryable = error.get("retryable") is True
                # Exec is not idempotent: replay only explicitly safe commands or a
                # documented retryable rejection indicating the workload did not run.
                if exc.code not in (429, 502, 503, 504) or not (
                    safe or idempotency or retryable
                ):
                    raise APIError(
                        exc.code, error.get("code", "request_failed")
                    ) from None
                delay = exc.headers.get("Retry-After", str(2**attempt))
                try:
                    delay = float(delay)
                except ValueError:
                    try:
                        from email.utils import parsedate_to_datetime

                        delay = max(
                            0, parsedate_to_datetime(delay).timestamp() - time.time()
                        )
                    except (ValueError, TypeError):
                        delay = 30
                if attempt == 3 or delay > 30:
                    raise APIError(
                        exc.code, error.get("code", "retry_budget_exhausted")
                    ) from None
                time.sleep(max(delay, 1))
            except (urllib.error.URLError, TimeoutError):
                if not (safe or idempotency) or attempt == 3:
                    raise RuntimeError(
                        "API transport outcome uncertain; unsafe replay refused"
                    ) from None
                time.sleep(2**attempt)
        raise RuntimeError("API retry budget exhausted")

    def execute(self, cmd: str, stdin: str = "", *, safe: bool = False) -> str:
        result = self.call(
            "POST",
            self.machine + "/exec",
            {"cmd": cmd, "stdin": stdin, "timeoutSeconds": 60},
            safe=safe,
        )
        if (
            result.get("timedOut")
            or result.get("truncated")
            or result.get("exitCode") != 0
        ):
            # Never print a raw response, command environment or potentially sensitive stderr.
            raise RuntimeError(
                f"Remote API command failed: exit={result.get('exitCode')}, "
                f"timeout={result.get('timedOut')}, truncated={result.get('truncated')}"
            )
        return result["stdout"]

    def ready(self, *, allow_resume: bool, run_id: str) -> dict:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            machine = self.call("GET", self.machine, safe=True)
            if machine.get("name") != "agent-development":
                raise RuntimeError("Secret machine does not identify agent-development")
            if machine.get("free") is not True:
                raise RuntimeError(
                    "No-spend policy: machine is not explicitly marked free by the API"
                )
            cooldown = machine.get("cooldownUntil")
            if cooldown and datetime.fromisoformat(
                cooldown.replace("Z", "+00:00")
            ) > datetime.now(timezone.utc):
                raise RuntimeError("Machine lifecycle cooldown active; not bypassed")
            if machine.get("maxRunMinutes") == 0:
                raise RuntimeError("Machine runtime cap is zero; not modified")
            operation = machine.get("operationId")
            if operation:
                result = self.call(
                    "GET",
                    "/v1/operations/"
                    + urllib.parse.quote(operation, safe="")
                    + "?wait=25s",
                    safe=True,
                )
                if result.get("state") == "failed":
                    raise RuntimeError("Existing lifecycle operation failed")
                continue
            if (
                machine.get("state") == "running"
                and machine.get("runtime", {}).get("ready") is True
            ):
                return machine
            if machine.get("autoSuspendedAt"):
                self.call("POST", self.machine + "/wake", {}, safe=True)
            elif machine.get("state") in ("suspended", "paused") and allow_resume:
                key = str(uuid.uuid5(uuid.NAMESPACE_URL, "lava-resume-" + run_id))
                operation = self.call(
                    "POST", self.machine + "/resume", {}, idempotency=key
                )
                op_id = operation.get("id")
                if not op_id:
                    raise RuntimeError("Resume returned no operation identity")
                self.call(
                    "GET",
                    "/v1/operations/"
                    + urllib.parse.quote(op_id, safe="")
                    + "?wait=25s",
                    safe=True,
                )
            elif machine.get("state") in ("starting", "resuming"):
                time.sleep(5)
            else:
                raise RuntimeError(
                    "Machine is manually paused/stopped; explicit authorized resume is required"
                )
        raise RuntimeError("Machine readiness deadline exceeded")


def stage_command(run_id: str, commit: str) -> str:
    # Fixed code + validated arguments. The source bundle contains Git objects, not auth config.
    code = r"""
import base64, json, os, pathlib, subprocess, sys
os.umask(0o077)
run_id, commit = sys.argv[1:]
root = pathlib.Path('/data/lava-ci')
if not pathlib.Path('/data').is_mount():
    raise RuntimeError('/data must be mounted')
root.mkdir(mode=0o700, exist_ok=True)
if root.is_symlink() or root.stat().st_uid != os.getuid():
    raise RuntimeError('Unsafe CI root owner/path')
(root/'runs').mkdir(mode=0o700, exist_ok=True)
run=root/'runs'/run_id
try:
    run.mkdir(mode=0o700)
except FileExistsError:
    print(json.dumps({'staged': True, 'existing': True}))
    sys.exit(0)
try:
    bundle=run/'source.bundle'
    bundle.write_bytes(base64.b64decode(sys.stdin.read(), validate=True))
    subprocess.run(['git','-c','core.hooksPath=/dev/null','clone','--no-checkout',str(bundle),str(run/'checkout')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(run/'checkout'),'checkout','--detach',commit],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    actual=subprocess.check_output(['git','-C',str(run/'checkout'),'rev-parse','HEAD'],text=True).strip()
    if actual!=commit:raise RuntimeError('Wrong commit')
    subprocess.Popen(['python3',str(run/'checkout/scripts/instabox_remote.py'),'--run-dir',str(run),'--commit',commit],cwd=run,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    print(json.dumps({'staged':True}))
except Exception:
    (run/'status.json').write_text(json.dumps({'state':'failed','exitCode':1,'error':'Source staging failed','commit':commit}))
    raise
"""
    return (
        "python3 -c "
        + shlex.quote(code)
        + " "
        + shlex.quote(run_id)
        + " "
        + shlex.quote(commit)
    )


def read_command(run_id: str) -> str:
    code = r"""
import json, pathlib, sys
run=pathlib.Path('/data/lava-ci/runs')/sys.argv[1]
status=run/'status.json'
result=json.loads(status.read_text()) if status.exists() else {'state':'pending'}
if result.get('state') in ('succeeded','failed'):
    log=run/'diagnostics.log'
    result['diagnostics']=log.read_text()[-65536:] if log.exists() else ''
print(json.dumps(result))
"""
    return "python3 -c " + shlex.quote(code) + " " + shlex.quote(run_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--allow-resume", action="store_true")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit) or not re.fullmatch(
        r"\d+-\d+", args.run_id
    ):
        raise RuntimeError("Invalid exact commit/run identity")
    os.umask(0o077)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    client = Client(
        os.environ.get("INSTABOX_API_KEY", ""),
        os.environ.get("INSTABOX_MACHINE_ID", ""),
    )
    machine = client.ready(allow_resume=args.allow_resume, run_id=args.run_id)
    print("Authenticated machine agent-development is running, ready and free-tier.")
    bundle = args.evidence_dir / "source.bundle"
    subprocess.run(
        ["git", "bundle", "create", str(bundle), "HEAD"],
        check=True,
        capture_output=True,
    )
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != args.commit:
        raise RuntimeError("Actions checkout does not match requested SHA")
    encoded = base64.b64encode(bundle.read_bytes()).decode()
    bundle.unlink()
    if len(encoded) > 1048576:
        raise RuntimeError("Source bundle exceeds API stdin limit; do not bypass limit")
    try:
        client.execute(stage_command(args.run_id, args.commit), encoded)
    except RuntimeError:
        # A lost response may mean the job started. Poll the run marker, never relaunch blindly.
        print("Launch response uncertain; inspecting owned run status without replay.")
    deadline = time.monotonic() + 1320
    pending = 0
    while time.monotonic() < deadline:
        result = json.loads(client.execute(read_command(args.run_id), safe=True))
        state = result.get("state")
        if state == "pending":
            pending += 1
            if pending >= 4:
                raise RuntimeError("No remote run marker; launch not replayed")
        if state in ("succeeded", "failed"):
            diagnostics = result.pop("diagnostics", "")
            result["observedMachine"] = machine["name"]
            if result.get("commit") != args.commit:
                raise RuntimeError("Remote evidence does not match intended commit")
            safe_log = redact(diagnostics, [client.key]).encode()[-65536:]
            (args.evidence_dir / "diagnostics.log").write_bytes(
                safe_log.decode(errors="ignore").encode()
            )
            (args.evidence_dir / "result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
            return 0 if state == "succeeded" and result.get("exitCode") == 0 else 1
        time.sleep(15)
    raise RuntimeError(
        "Remote job observation deadline exceeded; do not replay unknown work"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        # Errors expose codes and phases only; never HTTP bodies or secret-bearing commands.
        print(f"InstaBox gate failed: {type(error).__name__}: {error}")
        raise SystemExit(1) from None
