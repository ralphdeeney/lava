"""Deterministic policy preservation tests; not evidence of live admin access."""

from copy import deepcopy

import pytest

from engineering.configure_github import APP_ID, proposal


def baseline():
    return {
        "name": "Existing policy",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {"required_approving_review_count": 2},
            },
            {"type": "required_linear_history"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [
                        {"context": "security", "integration_id": 9}
                    ],
                },
            },
        ],
    }


def test_preserves_existing_protections_and_checks_without_mutating_snapshot():
    original = baseline()
    saved = deepcopy(original)
    result = proposal(original, "main")
    assert original == saved
    assert result["rules"][:-1] == original["rules"][:-1]
    parameters = result["rules"][-1]["parameters"]
    assert parameters["strict_required_status_checks_policy"] is True
    assert parameters["required_status_checks"] == [
        {"context": "security", "integration_id": 9},
        {"context": "engineering-controls", "integration_id": APP_ID},
        {"context": "checks", "integration_id": APP_ID},
    ]
    assert proposal(result, "main") == result


@pytest.mark.parametrize("change", ["bypass", "inactive", "wrong_branch", "exclusion"])
def test_refuses_ambiguous_or_unsafe_baseline(change):
    policy = baseline()
    if change == "bypass":
        policy["bypass_actors"] = [{"actor_id": 1}]
    elif change == "inactive":
        policy["enforcement"] = "evaluate"
    elif change == "wrong_branch":
        policy["conditions"]["ref_name"]["include"] = ["refs/heads/other"]
    else:
        policy["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
    with pytest.raises(ValueError):
        proposal(policy, "main")


def test_denial_never_reaches_automerge_settings(monkeypatch):
    from engineering import configure_github as config

    calls = []

    def fake_api(path, method="GET", payload=None):
        calls.append((path, method))
        if path == config.BASE:
            return {
                "default_branch": "main",
                "allow_auto_merge": False,
                "allow_squash_merge": True,
            }
        if method == "PUT":
            raise RuntimeError("403")
        return baseline()

    monkeypatch.setattr(config, "api", fake_api)
    with pytest.raises(RuntimeError, match="403"):
        config.configure(True)
    assert calls.count((config.RULESET, "PUT")) == 1
    assert not any(method == "PATCH" for _, method in calls)


def test_concurrent_edit_aborts_before_write(monkeypatch):
    from engineering import configure_github as config

    reads = 0

    def fake_api(path, method="GET", payload=None):
        nonlocal reads
        assert method == "GET"
        if path == config.BASE:
            return {"default_branch": "main"}
        reads += 1
        policy = baseline()
        if reads > 1:
            policy["name"] = "Another administrator edited policy"
        return policy

    monkeypatch.setattr(config, "api", fake_api)
    with pytest.raises(RuntimeError, match="changed during configuration"):
        config.configure(True)


def test_api_error_does_not_echo_arbitrary_cli_diagnostics(monkeypatch, capsys):
    from types import SimpleNamespace

    from engineering import configure_github as config

    def denied(*args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout='{"status":"403", "message":"sensitive-response-canary"}',
            stderr="sensitive-cli-canary",
        )

    monkeypatch.setattr(config.subprocess, "run", denied)
    with pytest.raises(RuntimeError) as error:
        config.api(config.RULESET, "PUT", {})
    assert "403" in str(error.value)
    assert "canary" not in str(error.value)
    assert "canary" not in capsys.readouterr().out
