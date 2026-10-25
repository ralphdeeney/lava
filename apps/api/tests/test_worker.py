"""Deterministic worker contracts that always run in CI."""

from lava.worker import SimulatedExecutor, _hash


def test_simulated_executor_supports_controlled_outcomes():
    assert SimulatedExecutor("success").run(lambda: False) == "success"
    assert SimulatedExecutor("failure").run(lambda: False) == "failure"
    assert SimulatedExecutor("timeout").run(lambda: False) == "retryable_failure"
    assert SimulatedExecutor("success").run(lambda: True) == "cancelled"


def test_lease_tokens_are_stored_as_sha256_digests():
    assert _hash("worker-token") != "worker-token"
    assert len(_hash("worker-token")) == 64
