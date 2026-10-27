"""Deterministic worker contracts that always run in CI."""

import pytest

from lava.core.settings import Settings
from lava.worker import SimulatedExecutor, _hash


def test_simulated_executor_supports_controlled_outcomes():
    assert SimulatedExecutor("success").run(lambda: False) == "success"
    assert SimulatedExecutor("failure").run(lambda: False) == "failure"
    assert SimulatedExecutor("timeout").run(lambda: False) == "retryable_failure"
    assert SimulatedExecutor("success").run(lambda: True) == "cancelled"


def test_lease_tokens_are_stored_as_sha256_digests():
    assert _hash("worker-token") != "worker-token"
    assert len(_hash("worker-token")) == 64


@pytest.mark.parametrize(
    "override",
    [
        {"worker_poll_interval_seconds": 0},
        {"worker_heartbeat_interval_seconds": 30},
        {"worker_concurrency": 2},
        {"worker_max_attempts": 0},
        {"worker_retry_backoff_seconds": 0},
    ],
)
def test_worker_rejects_unsafe_runtime_settings(override):
    with pytest.raises(ValueError):
        Settings(database_url="postgresql+psycopg://u:p@localhost/lava_test", **override)
