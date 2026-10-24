"""Synthetic JUnit parser fixtures; none are product or infrastructure acceptance evidence."""

import importlib.util
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

spec = importlib.util.spec_from_file_location(
    "control_plane_evals",
    Path(__file__).resolve().parents[2] / "evals/runners/control_plane.py",
)
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)

SHA = "a" * 40


def cases():
    return [
        {"id": f"EVAL-{number:03}", "critical": number in (3, 5, 6, 16, 17)}
        for number in range(1, 21)
    ]


def junit(tmp_path, *, source=SHA, environment="real-postgresql", change=None):
    document = ET.Element("testsuites")
    suite = ET.SubElement(document, "testsuite")
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", name="source_commit", value=source)
    ET.SubElement(properties, "property", name="test_environment", value=environment)
    for requirements in runner.MAPPINGS.values():
        for requirement in requirements:
            for index in range(requirement.minimum):
                name = (
                    requirement.name
                    if requirement.minimum == 1
                    else f"{requirement.name}[{index}]"
                )
                ET.SubElement(
                    suite, "testcase", classname=requirement.module, name=name
                )
    if change:
        change(suite)
    path = tmp_path / "synthetic-junit.xml"
    ET.ElementTree(document).write(path, encoding="utf-8", xml_declaration=True)
    return path


def report(path, *, clean=True):
    return runner.reconcile(
        cases(), [path], SHA, environment="real-postgresql", source_tree_clean=clean
    )


def test_synthetic_complete_mapping_is_only_slice_eligible(tmp_path):
    result = report(junit(tmp_path))
    assert result["slice_evaluations"]["eligible"] is True
    assert result["passed"] == len(runner.MAPPINGS)
    assert result["not_run"] == 20 - len(runner.MAPPINGS)
    assert result["mandatory_total"] == 20
    assert result["release_ready"] is False
    assert result["phase_release_ready"] is False
    assert result["browser_tests"] == "not_run"
    for case_id in (
        "EVAL-001",
        "EVAL-002",
        "EVAL-007",
        "EVAL-008",
        "EVAL-010",
        "EVAL-011",
        "EVAL-014",
        "EVAL-015",
        "EVAL-018",
        "EVAL-019",
        "EVAL-020",
    ):
        case = next(item for item in result["results"] if item["id"] == case_id)
        assert case["status"] == "not_run"


@pytest.mark.parametrize(
    "source,environment", [("b" * 40, "real-postgresql"), (SHA, "sqlite")]
)
def test_stale_or_wrong_environment_xml_is_blocked(tmp_path, source, environment):
    result = report(junit(tmp_path, source=source, environment=environment))
    assert result["slice_evaluations"]["eligible"] is False
    assert result["passed"] == 0
    assert result["blocked"] == len(runner.MAPPINGS)


def test_dirty_checkout_cannot_attribute_current_results_to_head(tmp_path):
    result = report(junit(tmp_path), clean=False)
    assert result["slice_evaluations"]["eligible"] is False
    assert result["source_tree_clean"] is False
    assert result["passed"] == 0


@pytest.mark.parametrize("tag", ["failure", "error", "skipped"])
def test_actual_failed_or_skipped_testcase_cannot_pass(tmp_path, tag):
    target = runner.MAPPINGS["EVAL-004"][0]

    def change(suite):
        testcase = next(
            item
            for item in suite.findall("testcase")
            if item.get("name") == target.name
        )
        ET.SubElement(testcase, tag)

    result = report(junit(tmp_path, change=change))
    assert result["slice_evaluations"]["eligible"] is False
    case = next(item for item in result["results"] if item["id"] == "EVAL-004")
    assert case["status"] == ("skipped" if tag == "skipped" else "failed")


def test_missing_named_assertion_remains_not_run(tmp_path):
    target = runner.MAPPINGS["EVAL-012"][0]

    def change(suite):
        suite.remove(
            next(
                item
                for item in suite.findall("testcase")
                if item.get("name") == target.name
            )
        )

    result = report(junit(tmp_path, change=change))
    case = next(item for item in result["results"] if item["id"] == "EVAL-012")
    assert case["status"] == "not_run"
    assert result["slice_evaluations"]["eligible"] is False


def test_duplicate_artifacts_do_not_overwrite_execution_failures(tmp_path):
    path = junit(tmp_path)
    result = runner.reconcile(
        cases(),
        [path, path],
        SHA,
        environment="real-postgresql",
        source_tree_clean=True,
    )
    assert result["passed"] == 0
    assert result["slice_evaluations"]["eligible"] is False
    assert any("Duplicate testcase" in issue for issue in result["artifact_problems"])


def test_unreadable_or_empty_reports_fail_closed(tmp_path):
    missing = tmp_path / "missing.xml"
    assert report(missing)["slice_evaluations"]["eligible"] is False
    missing.write_text("<testsuites/>")
    result = report(missing)
    assert result["slice_evaluations"]["eligible"] is False
    assert result["passed"] == 0


def test_testcase_property_cannot_replace_missing_suite_source_metadata(tmp_path):
    def change(suite):
        suite.remove(suite.find("properties"))

    result = report(junit(tmp_path, change=change))
    assert result["passed"] == 0
    assert result["slice_evaluations"]["eligible"] is False


def test_invalid_source_identity_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        runner.reconcile(
            cases(),
            [junit(tmp_path)],
            "short",
            environment="real-postgresql",
            source_tree_clean=True,
        )


@pytest.mark.parametrize("tag", ["failure", "error", "skipped"])
def test_unmapped_suite_failure_or_skip_still_blocks_slice(tmp_path, tag):
    def change(suite):
        testcase = ET.SubElement(
            suite, "testcase", classname="test_regression", name="test_other"
        )
        ET.SubElement(testcase, tag)

    result = report(junit(tmp_path, change=change))
    assert result["passed"] == len(runner.MAPPINGS)
    assert result["slice_evaluations"]["eligible"] is False


def test_insufficient_parameter_matrix_cannot_pass_the_scenario(tmp_path):
    target = runner.MAPPINGS["EVAL-009"][0]

    def change(suite):
        selected = [
            case
            for case in suite.findall("testcase")
            if case.get("name").split("[", 1)[0] == target.name
        ]
        assert len(selected) == 9
        suite.remove(selected[-1])

    result = report(junit(tmp_path, change=change))
    scenario = next(case for case in result["results"] if case["id"] == "EVAL-009")
    assert scenario["status"] == "not_run"
    assert result["slice_evaluations"]["eligible"] is False
