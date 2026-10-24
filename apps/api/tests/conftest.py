import os
from pathlib import Path
import subprocess

import pytest

os.environ.setdefault("LAVA_DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")


@pytest.fixture(scope="session", autouse=True)
def junit_source_provenance(record_testsuite_property):
    """Bind generated reports to actual checkout, without including configuration secrets."""
    root = Path(__file__).resolve().parents[3]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    record_testsuite_property("source_commit", sha)
    if os.environ.get("LAVA_INTEGRATION") == "1":
        record_testsuite_property("test_environment", "real-postgresql")
    else:
        record_testsuite_property("test_environment", "unit")
