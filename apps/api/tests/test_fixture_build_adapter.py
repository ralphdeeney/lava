"""Security tests for the adapter; these do not construct container images."""

from pathlib import Path

import pytest

from lava.builds.fixture_toolchain import (
    BUILDKIT_VERSION,
    FIXTURE_SHA256,
    RAILPACK_VERSION,
    fixture_digest,
    validate_trusted_source,
)


def test_real_build_is_rejected_outside_protected_main(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(PermissionError, match="protected trusted workflow"):
        validate_trusted_source(Path("/nonexistent"), "a" * 40, "python")


def test_pinned_fixture_inputs_and_versions_match_audited_source():
    root = Path(__file__).resolve().parents[3]
    assert RAILPACK_VERSION == "0.43.0"
    assert BUILDKIT_VERSION == "v0.34.0"
    for name, digest in FIXTURE_SHA256.items():
        assert fixture_digest(root / "build-fixtures" / name) == digest
