"""Permanent control-plane invariants for deployment lifecycle metadata."""

import pytest

from lava.application.deployments import STATUSES, TERMINAL, TRANSITIONS


def test_every_state_is_classified_and_terminal_states_have_no_outgoing_edges():
    assert set(TRANSITIONS) | TERMINAL == STATUSES
    assert not TERMINAL & set(TRANSITIONS)


def test_transitions_are_forward_only_and_reach_active_or_failure_terminal():
    for source, targets in TRANSITIONS.items():
        assert source not in targets
        assert targets <= STATUSES
    assert "active" in TRANSITIONS["verifying"]
    assert all(
        target in TERMINAL or target in STATUSES
        for targets in TRANSITIONS.values()
        for target in targets
    )


@pytest.mark.parametrize("terminal", sorted(TERMINAL))
def test_terminal_states_cannot_be_reentered(terminal):
    assert terminal not in TRANSITIONS
