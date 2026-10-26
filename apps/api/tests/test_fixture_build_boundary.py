"""Permanent regression checks for the trusted fixture-build boundary."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

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
