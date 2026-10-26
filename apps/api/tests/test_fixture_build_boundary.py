"""Permanent regression checks for the trusted fixture-build boundary."""

import subprocess
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _verifier():
    spec = spec_from_file_location("fixture_verifier", ROOT / "scripts/verify_fixture_builds.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audited_fixture_inputs_match_approved_digests(tmp_path):
    verifier = _verifier()
    for name, expected in verifier.FIXTURE_SHA256.items():
        assert verifier.fixture_digest(ROOT / "build-fixtures" / name) == expected

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "main.py").write_text("print('safe')\n")
    before = verifier.fixture_digest(fixture)
    (fixture / "main.py").write_text("print('changed')\n")
    assert verifier.fixture_digest(fixture) != before
    (fixture / "linked.py").symlink_to(fixture / "main.py")
    with pytest.raises(RuntimeError, match="symlinks"):
        verifier.fixture_digest(fixture)


def test_docker_capable_fixture_job_is_protected_main_only():
    workflow = (ROOT / ".github/workflows/fixture-builds.yml").read_text()
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert "pull_request_target:" not in workflow
    assert 'LAVA_TRUSTED_FIXTURE_CI: "1"' in workflow


def test_protected_promotion_accepts_only_exact_candidate_identity(monkeypatch):
    from lava.builds import fixture_toolchain

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    monkeypatch.setattr(
        fixture_toolchain.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=5 * 1024**3),
    )
    for key, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "ralphdeeney/lava",
        "GITHUB_SHA": "32dc0cf71ff0c042842d56d8884e3d2f61db1197",
        "LAVA_PROMOTED_SOURCE_SHA": commit,
    }.items():
        monkeypatch.setenv(key, value)
    assert fixture_toolchain.validate_trusted_source(ROOT, commit, "python") == (
        ROOT / "build-fixtures/python"
    )
    for key, value in (
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REF", "refs/pull/9/merge"),
        ("LAVA_PROMOTED_SOURCE_SHA", "0" * 40),
        ("GITHUB_REPOSITORY", "attacker/fork"),
    ):
        monkeypatch.setenv(key, value)
        with pytest.raises(PermissionError):
            fixture_toolchain.validate_trusted_source(ROOT, commit, "python")
        monkeypatch.setenv(
            key,
            {
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/main",
                "LAVA_PROMOTED_SOURCE_SHA": commit,
                "GITHUB_REPOSITORY": "ralphdeeney/lava",
            }[key],
        )
