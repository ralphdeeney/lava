from dataclasses import replace
from uuid import uuid4

import pytest

from lava.application.executor_protocol import ExecutorRequest, authenticate, sign

KEY = b"disposable-test-key-only-32-bytes!"


def request():
    return ExecutorRequest(
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        1,
        "a" * 40,
        1,
        "python",
        "start",
        "b" * 64,
        1030,
        lease_owner="test-worker",
        lease_token="test-lease-token",
    )


def test_authenticated_identity_cannot_be_modified():
    value = request()
    signature = sign(value, KEY)
    authenticate(value, signature, KEY, now=1000)
    for field, change in {
        "operation": "cancel",
        "claim_generation": 2,
        "source_commit": "c" * 40,
        "configuration_revision": 2,
        "deployment_id": str(uuid4()),
    }.items():
        with pytest.raises(PermissionError):
            authenticate(replace(value, **{field: change}), signature, KEY, now=1000)


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": 1000},
        {"expires_at": 1061},
        {"fixture": "customer"},
        {"claim_generation": 0},
        {"source_commit": "main"},
        {"nonce": "short"},
    ],
)
def test_even_authenticated_invalid_requests_are_rejected(changes):
    value = replace(request(), **changes)
    with pytest.raises(ValueError):
        authenticate(value, sign(value, KEY), KEY, now=1000)
