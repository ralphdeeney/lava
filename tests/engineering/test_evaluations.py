"""Evaluation accounting tests use synthetic observations, not product acceptance results."""

from copy import deepcopy
import json

import pytest

from engineering.evaluations import catalog, evaluate

SHA = "a" * 40
OTHER_SHA = "b" * 40


def cases():
    return [{"id": f"EVAL-{index:03}", "critical": index in (3, 5, 6)} for index in range(1, 21)]


def observations():
    return [
        {
            "id": case["id"],
            "source_commit": SHA,
            "status": "passed",
            "executed": True,
            "simulated": False,
            "evidence": f"artifact://synthetic-fixture/{case['id']}",
            "reason": "Synthetic accounting fixture only",
        }
        for case in cases()
    ]


def test_twenty_valid_fixture_observations_have_exact_totals():
    report = evaluate(cases(), observations(), SHA)
    assert report["mandatory_total"] == 20
    assert report["passed"] == 20
    assert report["failed"] == report["skipped"] == report["blocked"] == report["not_run"] == 0
    assert report["critical_security_failures"] == 0
    assert report["source_commit"] == SHA
    assert report["release_ready"] is True


def test_missing_product_evidence_remains_not_run():
    report = evaluate(cases(), [], SHA)
    assert report["passed"] == 0
    assert report["not_run"] == 20
    assert report["release_ready"] is False
    assert all(item["reason"] == "No executed acceptance evidence" for item in report["results"])


@pytest.mark.parametrize(
    "field,value",
    [("source_commit", OTHER_SHA), ("executed", False), ("simulated", True), ("evidence", "")],
)
def test_stale_unexecuted_or_simulated_observations_cannot_pass(field, value):
    evidence = observations()
    evidence[0][field] = value
    report = evaluate(cases(), evidence, SHA)
    assert report["passed"] == 19
    assert report["blocked"] == 1
    assert report["release_ready"] is False


@pytest.mark.parametrize("field", ["source_commit", "executed", "simulated", "evidence"])
def test_missing_execution_metadata_cannot_pass(field):
    evidence = observations()
    del evidence[0][field]
    assert evaluate(cases(), evidence, SHA)["blocked"] == 1


def test_duplicate_observations_are_rejected_instead_of_overwriting_a_failure():
    evidence = observations()
    evidence.append({**evidence[0], "status": "failed"})
    with pytest.raises(ValueError, match="Duplicate observations"):
        evaluate(cases(), evidence, SHA)


def test_critical_security_failure_blocks_release():
    evidence = observations()
    evidence[4]["status"] = "failed"
    report = evaluate(cases(), evidence, SHA)
    assert report["critical_security_failures"] == 1
    assert report["failed"] == 1
    assert report["release_ready"] is False


def test_skips_and_blockers_are_not_silently_counted_as_passes():
    evidence = observations()
    evidence[0]["status"] = "skipped"
    evidence[1]["status"] = "blocked"
    report = evaluate(cases(), evidence, SHA)
    assert (report["passed"], report["skipped"], report["blocked"]) == (18, 1, 1)
    assert report["release_ready"] is False


def test_unknown_status_is_rejected():
    evidence = observations()
    evidence[0]["status"] = "probably fine"
    with pytest.raises(ValueError, match="Unknown evaluation status"):
        evaluate(cases(), evidence, SHA)


def test_catalog_loads_json_subset_of_yaml(tmp_path):
    (tmp_path / "authentication.yaml").write_text(json.dumps(cases()[:10]))
    (tmp_path / "authorization.yaml").write_text(json.dumps(cases()[10:]))
    loaded = catalog(tmp_path)
    assert [case["id"] for case in loaded] == [case["id"] for case in cases()]


def test_duplicate_catalog_ids_are_rejected(tmp_path):
    (tmp_path / "first.yaml").write_text(json.dumps(cases()))
    (tmp_path / "second.yaml").write_text(json.dumps([cases()[0]]))
    with pytest.raises(ValueError, match="unique and nonempty"):
        catalog(tmp_path)


def test_empty_catalog_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unique and nonempty"):
        catalog(tmp_path)


def test_evaluation_accounting_does_not_mutate_original_evidence():
    source_cases = cases()
    source_observations = observations()
    original = deepcopy((source_cases, source_observations))
    evaluate(source_cases, source_observations, SHA)
    assert (source_cases, source_observations) == original



def test_direct_empty_case_collection_is_rejected():
    with pytest.raises(ValueError):
        evaluate([], [], SHA)


def test_direct_duplicate_case_ids_are_rejected():
    duplicate_cases = [*cases(), cases()[0]]
    with pytest.raises(ValueError):
        evaluate(duplicate_cases, observations(), SHA)


@pytest.mark.parametrize("invalid_sha", ["short", "g" * 40, "A" * 40, ""])
def test_evaluator_rejects_invalid_full_commit_identity(invalid_sha):
    evidence = observations()
    for observation in evidence:
        observation["source_commit"] = invalid_sha
    with pytest.raises(ValueError):
        evaluate(cases(), evidence, invalid_sha)
