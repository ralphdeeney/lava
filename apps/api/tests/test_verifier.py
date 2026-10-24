"""Safety tests for the operator-facing integration gate."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "verify_instabox", Path(__file__).resolve().parents[3] / "scripts/verify_instabox.py"
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def safe_config():
    return {
        "services": {
            "db": {},
            "api": {"ports": [{"host_ip": "127.0.0.1"}]},
            "web": {"ports": [{"host_ip": "127.0.0.1"}]},
        }
    }


@pytest.mark.parametrize("violation", ["database", "socket", "privileged", "public_http"])
def test_exposure_guard(violation):
    config = copy.deepcopy(safe_config())
    verifier.assert_safe_config(config)
    services = config["services"]
    if violation == "database":
        services["db"]["ports"] = [{"published": "5432"}]
    elif violation == "socket":
        services["api"]["volumes"] = [{"source": "/var/run/docker.sock", "target": "/socket"}]
    elif violation == "privileged":
        services["api"]["privileged"] = True
    else:
        services["web"]["ports"][0]["host_ip"] = "0.0.0.0"
    with pytest.raises(RuntimeError):
        verifier.assert_safe_config(config)


def test_diagnostic_redaction():
    result = verifier.redact(
        "postgresql+psycopg://user:password@db/lava token=abc password=def known-secret "
        "https://proxyuser:proxypass@proxy.example",
        ["known-secret"],
    )
    for secret in ("user:password", "abc", "def", "known-secret", "proxyuser", "proxypass"):
        assert secret not in result


def test_unmounted_data_directory_is_rejected(tmp_path):
    with pytest.raises(RuntimeError, match="separate mounted"):
        verifier.database_storage_guard(tmp_path, tmp_path, False)


def test_startup_failure_cleans_only_owned_project_and_redacts_logs(tmp_path, monkeypatch):
    calls = []
    passwords = []

    def run(argv, **kwargs):
        calls.append(argv)
        output = ""
        code = 0
        if argv[:2] == ["node", "--version"]:
            output = "v22.23.3"
        elif argv[:2] == ["uv", "--version"]:
            output = "uv 0.12.23 (test)"
        elif argv[1:3] == ["compose", "version"]:
            output = "5.6.0"
        elif argv[1] == "info":
            output = json.dumps({"DockerRootDir": str(tmp_path), "ServerVersion": "29.8.2"})
        elif "--format" in argv and "config" in argv:
            output = json.dumps(safe_config())
        elif "up" in argv:
            envfile = Path(argv[argv.index("--env-file") + 1])
            password = next(
                line.split("=", 1)[1]
                for line in envfile.read_text().splitlines()
                if line.startswith("POSTGRES_PASSWORD=")
            )
            passwords.append(password)
            output = f"Startup failed; password={password}" + "é" * 70000
            code = 1
        return subprocess.CompletedProcess(argv, code, output)

    monkeypatch.setattr(verifier.subprocess, "run", run)
    monkeypatch.setattr(
        sys, "argv", ["verify", "--data-dir", str(tmp_path), "--allow-root-storage"]
    )
    assert verifier.main() == 1
    downs = [call for call in calls if "down" in call]
    assert len(downs) == 1
    project = downs[0][downs[0].index("--project-name") + 1]
    assert project.startswith("lava-verify-")
    assert "--volumes" in downs[0]
    assert not any("prune" in call or "--remove-orphans" in call for call in calls)
    assert not list(tmp_path.rglob("compose.env"))
    logs = list(tmp_path.rglob("commands.log"))
    assert logs and passwords
    for log in logs:
        assert passwords[0] not in log.read_text()
        assert log.stat().st_size <= 65536
        assert log.stat().st_mode & 0o077 == 0
