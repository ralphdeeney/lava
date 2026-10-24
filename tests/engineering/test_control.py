"""Deterministic orchestration policy tests; these do not configure GitHub or run a VM."""

from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from engineering.control import PolicyError, Slice, Store, assess_merge

SHA = "a" * 40
REPAIR_SHA = "b" * 40
MERGED_SHA = "c" * 40


def slice_record(**changes):
    return Slice(
        phase="01",
        slice_id="pipeline",
        branch="feat/autonomous-phase01-pipeline",
        source_commit=SHA,
        **changes,
    )


def outcome(name="unit", status="passed", executed=True):
    return {"name": name, "status": status, "executed": executed, "simulated": False}


def valid_gate():
    policy = {
        "protection_verified": True,
        "enforce_admins": True,
        "bypass_actors": [],
        "auto_merge_enabled": True,
        "squash_enabled": True,
        "required_checks": ["checks", "integration"],
    }
    evidence = {
        "source_commit": SHA,
        "scope_authorized": True,
        "mergeable": True,
        "approvals_satisfied": True,
        "checks": {
            name: {"source_commit": SHA, "conclusion": "success"}
            for name in policy["required_checks"]
        },
        "security": {"independent": True, "executed": True, "simulated": False, "critical_findings": 0, "source_commit": SHA},
        "evals": {
            "source_commit": SHA,
            "simulated": False,
            "executed": True,
            "mandatory_total": 20,
            "passed": 20,
            "failed": 0,
            "skipped": 0,
        },
        "instabox": {
            "simulated": False,
            "executed": True,
            "status": "succeeded",
            "source_commit": SHA,
            "exitCode": 0,
        },
    }
    return policy, evidence


def test_initial_failure_records_the_complete_aggregate():
    value = slice_record()
    results = [
        outcome("unit", "failed"),
        outcome("security", "failed"),
        outcome("browser", "not_run", False),
    ]
    value.verification(results, source_commit=SHA)
    assert value.state == "DIAGNOSE"
    assert value.repair_attempts == 0
    assert value.runs == [{"source_commit": SHA, "kind": "initial", "results": results}]


def test_one_repair_and_one_failed_retest_exhaust_the_budget():
    value = slice_record()
    value.verification([outcome(status="failed")], source_commit=SHA)
    value.repair("A missing package broke both checks", REPAIR_SHA)
    assert value.state == "REPAIR"
    assert value.repair_attempts == 1
    assert value.source_commit == REPAIR_SHA
    value.verification([outcome(status="failed")], source_commit=REPAIR_SHA)
    assert value.state == "BLOCKED"
    assert [run["kind"] for run in value.runs] == ["initial", "retest"]
    with pytest.raises(PolicyError):
        value.repair("Another attempted repair", MERGED_SHA)
    with pytest.raises(PolicyError):
        value.verification([outcome()], source_commit=REPAIR_SHA)


def test_successful_single_retest_can_continue_to_pr():
    value = slice_record()
    value.verification([outcome(status="failed")], source_commit=SHA)
    value.repair("Corrected the isolated cause", REPAIR_SHA)
    value.verification([outcome()], source_commit=REPAIR_SHA)
    value.open_pr("https://github.com/ralphdeeney/lava/pull/2")
    assert value.state == "PR_OPEN"
    assert value.repair_attempts == 1


@pytest.mark.parametrize(
    "results,commit",
    [
        ([outcome()], REPAIR_SHA),
        ([outcome(executed=False)], SHA),
        ([], SHA),
        ([outcome(), outcome()], SHA),
        ([outcome(status="unexpected")], SHA),
    ],
)
def test_invalid_initial_evidence_cannot_change_state(results, commit):
    value = slice_record()
    with pytest.raises(PolicyError):
        value.verification(results, source_commit=commit)
    assert value.state == "IMPLEMENT"
    assert value.runs == []


def test_initial_verification_cannot_be_repeated_to_hide_a_failure():
    value = slice_record()
    value.verification([outcome(status="failed")], source_commit=SHA)
    with pytest.raises(PolicyError):
        value.verification([outcome()], source_commit=SHA)
    assert value.state == "DIAGNOSE"
    assert len(value.runs) == 1


@pytest.mark.parametrize("diagnosis,new_commit", [("", REPAIR_SHA), ("cause", SHA), ("cause", "short")])
def test_repair_requires_diagnosis_and_new_exact_commit(diagnosis, new_commit):
    value = slice_record()
    value.verification([outcome(status="failed")], source_commit=SHA)
    with pytest.raises(PolicyError):
        value.repair(diagnosis, new_commit)
    assert value.repair_attempts == 0


def test_rejected_store_mutation_preserves_previous_durable_record(tmp_path):
    path = tmp_path / "progress.json"
    initial = asdict(slice_record())
    path.write_text(json.dumps(initial))

    def rejected(value):
        value.state = "BLOCKED"
        value.repair_attempts = 2

    with pytest.raises(PolicyError):
        Store(path).update(rejected)
    assert json.loads(path.read_text()) == initial
    assert not path.with_suffix(".tmp").exists()


def test_store_persists_the_repair_budget_across_reload(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps(asdict(slice_record())))
    store = Store(path)
    store.update(lambda value: value.verification([outcome(status="failed")], source_commit=SHA))
    store.update(lambda value: value.repair("Isolated cause", REPAIR_SHA))
    Store(path).update(
        lambda value: value.verification([outcome(status="failed")], source_commit=REPAIR_SHA)
    )
    saved = json.loads(path.read_text())
    assert saved["state"] == "BLOCKED"
    assert saved["repair_attempts"] == 1
    assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(PolicyError):
        Store(path).update(lambda value: value.repair("Retry after reload", MERGED_SHA))


@pytest.mark.parametrize(
    "observation",
    [
        {"merged": False, "head_sha": SHA, "merge_commit": MERGED_SHA},
        {"auto_merge_enabled": True, "head_sha": SHA},
        {"merged": True, "head_sha": REPAIR_SHA, "merge_commit": MERGED_SHA},
        {"merged": True, "head_sha": SHA, "merge_commit": "short"},
    ],
)
def test_enabling_automerge_is_not_a_completed_merge(observation):
    value = slice_record(state="AUTOMERGE_ENABLED")
    with pytest.raises(PolicyError):
        value.confirm_merge(observation)
    assert value.state == "AUTOMERGE_ENABLED"
    assert value.merged_commit is None


def test_actual_matching_merge_evidence_advances_the_slice():
    value = slice_record(state="AUTOMERGE_ENABLED")
    value.confirm_merge({"merged": True, "head_sha": SHA, "merge_commit": MERGED_SHA})
    assert value.state == "MERGED"
    assert value.merged_commit == MERGED_SHA


def test_complete_gate_fixture_is_accepted():
    policy, evidence = valid_gate()
    assert assess_merge(policy, evidence, SHA) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("protection_verified", False),
        ("protection_verified", None),
        ("enforce_admins", False),
        ("bypass_actors", ["coding-agent"]),
        ("auto_merge_enabled", False),
        ("squash_enabled", False),
        ("required_checks", []),
    ],
)
def test_unknown_or_unsafe_repository_policy_blocks_merging(field, value):
    policy, evidence = valid_gate()
    policy[field] = value
    assert assess_merge(policy, evidence, SHA)


@pytest.mark.parametrize("section", ["checks", "security", "evals", "instabox"])
def test_missing_required_evidence_blocks_merging(section):
    policy, evidence = valid_gate()
    del evidence[section]
    assert assess_merge(policy, evidence, SHA)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("security", "independent", False),
        ("security", "critical_findings", 1),
        ("security", "critical_findings", None),
        ("evals", "executed", False),
        ("evals", "passed", 19),
        ("evals", "failed", 1),
        ("evals", "skipped", 1),
        ("evals", "mandatory_total", 0),
        ("instabox", "executed", False),
        ("instabox", "source_commit", REPAIR_SHA),
        ("instabox", "status", "not_run"),
        ("instabox", "exitCode", 1),
    ],
)
def test_security_evaluation_and_infrastructure_failures_block_merging(section, field, value):
    policy, evidence = valid_gate()
    evidence[section][field] = value
    assert assess_merge(policy, evidence, SHA)


def test_stale_successful_status_check_cannot_satisfy_current_head():
    policy, evidence = valid_gate()
    evidence["checks"]["checks"]["source_commit"] = REPAIR_SHA
    blockers = assess_merge(policy, evidence, SHA)
    assert any("required check not successful for exact head: checks" in reason for reason in blockers)


@pytest.mark.parametrize("field", ["scope_authorized", "mergeable", "approvals_satisfied"])
def test_unverified_authorization_or_approvals_block_merging(field):
    policy, evidence = valid_gate()
    evidence[field] = False
    assert assess_merge(policy, evidence, SHA)


def test_merge_assessment_does_not_mutate_its_observations():
    policy, evidence = valid_gate()
    original = deepcopy((policy, evidence))
    assess_merge(policy, evidence, SHA)
    assert (policy, evidence) == original


@pytest.mark.parametrize("section", ["security", "evals"])
@pytest.mark.parametrize("source_commit", [None, REPAIR_SHA])
def test_nested_review_and_eval_evidence_must_match_the_exact_head(section, source_commit):
    policy, evidence = valid_gate()
    if source_commit is None:
        del evidence[section]["source_commit"]
    else:
        evidence[section]["source_commit"] = source_commit
    assert assess_merge(policy, evidence, SHA)


@pytest.mark.parametrize("simulated", [True, None])
def test_vm_evidence_must_explicitly_be_nonsimulated(simulated):
    policy, evidence = valid_gate()
    if simulated is None:
        del evidence["instabox"]["simulated"]
    else:
        evidence["instabox"]["simulated"] = simulated
    assert assess_merge(policy, evidence, SHA)


@pytest.mark.parametrize("invalid_sha", ["short", "g" * 40, "A" * 40, ""])
def test_merge_gate_rejects_invalid_full_commit_identity(invalid_sha):
    policy, evidence = valid_gate()
    evidence["source_commit"] = invalid_sha
    for observation in evidence["checks"].values():
        observation["source_commit"] = invalid_sha
    for section in ("security", "evals", "instabox"):
        evidence[section]["source_commit"] = invalid_sha
    assert assess_merge(policy, evidence, invalid_sha)


def test_simulated_aggregate_success_is_rejected():
    value = slice_record()
    with pytest.raises(PolicyError):
        value.verification([{**outcome(), "simulated": True}], source_commit=SHA)
    assert value.state == "IMPLEMENT"
