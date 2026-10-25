"""Synthetic accounting fixtures; these are not real Slice 01.3 acceptance evidence."""

import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

spec = importlib.util.spec_from_file_location(
    "tenancy_evals",
    Path(__file__).resolve().parents[2] / "evals/runners/tenancy.py",
)
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)
SHA = "a" * 40


def fixtures(tmp_path):
    suite = ET.Element("testsuite")
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", name="source_commit", value=SHA)
    ET.SubElement(
        properties, "property", name="test_environment", value="real-postgresql"
    )
    for requirements in runner.browser.backend.MAPPINGS.values():
        for requirement in requirements:
            for index in range(requirement.minimum):
                ET.SubElement(
                    suite,
                    "testcase",
                    classname=requirement.module,
                    name=f"{requirement.name}[{index}]",
                )
    for name in runner.browser.AUTH_MAPPINGS.values():
        ET.SubElement(suite, "testcase", classname="test_browser_auth", name=name)
    for name, minimum in (
        runner.browser.GUARDS | runner.browser.SECURITY_GUARDS
    ).items():
        for index in range(minimum):
            ET.SubElement(
                suite,
                "testcase",
                classname="test_browser_security"
                if name in runner.browser.SECURITY_GUARDS
                else "test_browser_auth",
                name=f"{name}[{index}]",
            )
    for name in set(runner.SECURITY_GUARDS):
        ET.SubElement(suite, "testcase", classname="test_tenancy_security", name=name)
    for name in {requirement[0] for requirement in runner.REQUIREMENTS.values()}:
        ET.SubElement(suite, "testcase", classname="test_tenancy", name=name)
    junit = tmp_path / "synthetic.xml"
    ET.ElementTree(suite).write(junit)
    browser = tmp_path / "synthetic-browser.json"
    browser.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runner_status": "passed",
                "source_commit": SHA,
                "source_tree_clean": True,
                "test_environment": "real-browser-postgresql",
                "executed": True,
                "simulated": False,
                "tests": [
                    {
                        "name": name,
                        "project": project,
                        "status": "passed",
                        "viewport": {
                            "width": 1280 if project == "desktop" else 390,
                            "height": 900 if project == "desktop" else 844,
                        },
                    }
                    for name in (
                        runner.browser.BROWSER_NAMES
                        + runner.browser.TENANCY_BROWSER_NAMES
                    )
                    for project in runner.browser.PROJECTS
                ],
            }
        )
    )
    return junit, browser


def reconcile(junit, browser, *, clean=True):
    cases = [{"id": f"EVAL-{index:03}"} for index in range(1, 21)]
    return runner.reconcile(cases, [junit], browser, SHA, source_tree_clean=clean)


def test_complete_synthetic_scope_is_fifteen_of_twenty(tmp_path):
    report = reconcile(*fixtures(tmp_path))
    assert report["slice_evaluations"]["applicable"] == 15
    assert report["slice_evaluations"]["eligible"]
    assert (report["passed"], report["not_run"]) == (15, 5)
    assert report["browser_tests"] == {
        "total": 26,
        "passed": 26,
        "failed": 0,
        "skipped": 0,
        "all_required_journeys_passed": True,
    }
    assert all(report["mandatory_tenancy_guards"].values())
    assert not report["release_ready"]


@pytest.mark.parametrize("missing", runner.SECURITY_GUARDS)
def test_missing_security_guard_blocks(tmp_path, missing):
    junit, browser = fixtures(tmp_path)
    document = ET.parse(junit)
    suite = document.getroot()
    suite.remove(
        next(item for item in suite.findall("testcase") if item.get("name") == missing)
    )
    document.write(junit)
    report = reconcile(junit, browser)
    assert not report["mandatory_tenancy_guards"][missing]
    assert not report["slice_evaluations"]["eligible"]


def test_missing_mobile_environment_journey_blocks(tmp_path):
    junit, browser = fixtures(tmp_path)
    report = json.loads(browser.read_text())
    report["tests"] = [
        item
        for item in report["tests"]
        if (item["name"], item["project"])
        != (runner.browser.TENANCY_BROWSER_NAMES[3], "mobile")
    ]
    browser.write_text(json.dumps(report))
    outcome = reconcile(junit, browser)
    assert not outcome["browser_tests"]["all_required_journeys_passed"]
    assert not outcome["slice_evaluations"]["eligible"]


def test_missing_railpack_database_assertion_keeps_eval008_unrun(tmp_path):
    junit, browser = fixtures(tmp_path)
    document = ET.parse(junit)
    suite = document.getroot()
    suite.remove(
        next(
            item
            for item in suite.findall("testcase")
            if item.get("name") == runner.REQUIREMENTS["EVAL-008"][0]
        )
    )
    document.write(junit)
    report = reconcile(junit, browser)
    assert (
        next(result for result in report["results"] if result["id"] == "EVAL-008")[
            "status"
        ]
        == "not_run"
    )
    assert not report["slice_evaluations"]["eligible"]


def test_failed_or_stale_browser_evidence_blocks(tmp_path):
    junit, browser = fixtures(tmp_path)
    report = json.loads(browser.read_text())
    report["tests"][-1]["status"] = "failed"
    report["runner_status"] = "failed"
    browser.write_text(json.dumps(report))
    assert not reconcile(junit, browser)["slice_evaluations"]["eligible"]
    report["source_commit"] = "b" * 40
    browser.write_text(json.dumps(report))
    assert not reconcile(junit, browser)["slice_evaluations"]["eligible"]


def test_dirty_source_blocks_synthetic_evidence(tmp_path):
    report = reconcile(*fixtures(tmp_path), clean=False)
    assert not report["slice_evaluations"]["eligible"]
