"""Synthetic report fixtures test reconciliation, never product/browser acceptance."""

import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

spec = importlib.util.spec_from_file_location(
    "browser_auth_evals",
    Path(__file__).resolve().parents[2] / "evals/runners/browser_auth.py",
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
    for requirements in runner.backend.MAPPINGS.values():
        for requirement in requirements:
            for index in range(requirement.minimum):
                ET.SubElement(
                    suite,
                    "testcase",
                    classname=requirement.module,
                    name=f"{requirement.name}[{index}]",
                )
    for name in runner.AUTH_MAPPINGS.values():
        ET.SubElement(suite, "testcase", classname="test_browser_auth", name=name)
    for name, minimum in (runner.GUARDS | runner.SECURITY_GUARDS).items():
        for index in range(minimum):
            ET.SubElement(
                suite,
                "testcase",
                classname="test_browser_security"
                if name in runner.SECURITY_GUARDS
                else "test_browser_auth",
                name=f"{name}[{index}]",
            )
    junit = tmp_path / "synthetic.xml"
    ET.ElementTree(suite).write(junit)
    browser = tmp_path / "synthetic-browser.json"
    report = {
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
            for name in runner.BROWSER_NAMES
            for project in runner.PROJECTS
        ],
    }
    browser.write_text(json.dumps(report))
    return junit, browser


def reconcile(junit, browser, clean=True):
    cases = [{"id": f"EVAL-{i:03}"} for i in range(1, 21)]
    return runner.reconcile(cases, [junit], browser, SHA, source_tree_clean=clean)


def change_browser(path, change):
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def test_synthetic_complete_scope_never_releases_phase(tmp_path):
    result = reconcile(*fixtures(tmp_path))
    assert result["slice_evaluations"]["eligible"]
    assert result["passed"] == 13
    assert result["not_run"] == 7
    assert not result["release_ready"]
    assert not result["phase_release_ready"]
    assert all(result["mandatory_session_guards"].values())
    assert (
        "not public registration"
        in next(item for item in result["results"] if item["id"] == "EVAL-001")[
            "reason"
        ]
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_commit", "b" * 40),
        ("source_tree_clean", False),
        ("test_environment", "mock-browser"),
        ("executed", False),
        ("simulated", True),
        ("schema_version", 2),
        ("runner_status", "failed"),
        ("runner_status", "timedout"),
    ],
)
def test_invalid_execution_metadata_blocks(tmp_path, key, value):
    junit, browser = fixtures(tmp_path)
    change_browser(browser, lambda data: data.update({key: value}))
    assert not reconcile(junit, browser)["slice_evaluations"]["eligible"]


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_any_browser_failure_or_skip_blocks(tmp_path, status):
    junit, browser = fixtures(tmp_path)
    change_browser(browser, lambda data: data["tests"][-1].update(status=status))
    assert not reconcile(junit, browser)["slice_evaluations"]["eligible"]


def test_missing_mobile_observation_blocks(tmp_path):
    junit, browser = fixtures(tmp_path)
    change_browser(browser, lambda data: data["tests"].pop())
    assert not reconcile(junit, browser)["slice_evaluations"]["eligible"]


def test_duplicate_browser_observations_block(tmp_path):
    junit, browser = fixtures(tmp_path)
    change_browser(browser, lambda data: data["tests"].append(data["tests"][0]))
    assert not reconcile(junit, browser)["slice_evaluations"]["eligible"]


def test_unknown_secret_bearing_test_fields_are_not_published(tmp_path):
    junit, browser = fixtures(tmp_path)
    secret = "secret-placeholder-not-real"
    change_browser(browser, lambda data: data["tests"][0].update(error=secret))
    result = reconcile(junit, browser)
    assert not result["slice_evaluations"]["eligible"]
    assert secret not in json.dumps(result)


def test_wrong_viewport_cannot_claim_mobile(tmp_path):
    junit, browser = fixtures(tmp_path)
    change_browser(
        browser,
        lambda data: data["tests"][1].update(viewport={"width": 1280, "height": 900}),
    )
    assert not reconcile(junit, browser)["slice_evaluations"]["eligible"]


def test_missing_backend_security_guard_blocks(tmp_path):
    junit, browser = fixtures(tmp_path)
    document = ET.parse(junit)
    suite = document.getroot()
    suite.remove(
        next(
            item
            for item in suite.findall("testcase")
            if item.get("name").startswith(
                "test_browser_mutations_require_origin_and_csrf"
            )
        )
    )
    document.write(junit)
    result = reconcile(junit, browser)
    assert not result["mandatory_session_guards"][
        "test_browser_mutations_require_origin_and_csrf"
    ]
    assert not result["slice_evaluations"]["eligible"]


def test_unrelated_backend_failure_blocks(tmp_path):
    junit, browser = fixtures(tmp_path)
    document = ET.parse(junit)
    test = ET.SubElement(
        document.getroot(), "testcase", classname="elsewhere", name="test_failure"
    )
    ET.SubElement(test, "failure", message="sanitized by runner")
    document.write(junit)
    assert not reconcile(junit, browser)["slice_evaluations"]["eligible"]


def test_dirty_checkout_blocks_all_acceptance(tmp_path):
    result = reconcile(*fixtures(tmp_path), clean=False)
    assert not result["slice_evaluations"]["eligible"]
    assert result["passed"] == 0


@pytest.mark.parametrize("raw", ["{}", "[]", "broken JSON"])
def test_malformed_browser_reports_block(tmp_path, raw):
    junit, browser = fixtures(tmp_path)
    browser.write_text(raw)
    assert not reconcile(junit, browser)["slice_evaluations"]["eligible"]
