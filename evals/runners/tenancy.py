#!/usr/bin/env python3
"""Reconcile Slice 01.3 real PostgreSQL and browser evidence; never grant merge authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_auth as browser  # noqa: E402

from engineering.evaluations import catalog, evaluate  # noqa: E402

REQUIREMENTS = {
    "EVAL-007": (
        "test_environment_project_isolation_and_unique_slug",
        "project environments stay isolated and archived metadata is immutable",
    ),
    "EVAL-008": (
        "test_railpack_service_configuration_metadata",
        "invited developer gains access and loses it immediately on revocation",
    ),
}
SECURITY_GUARDS = (
    "test_revoked_member_immediately_denied",
    "test_final_owner_cannot_be_removed_or_demoted",
    "test_member_cannot_escalate_roles",
    "test_invitation_single_use_expiry_and_revocation",
)


def reconcile(cases, junit, browser_report, sha, *, source_tree_clean):
    previous = browser.reconcile(
        cases, junit, browser_report, sha, source_tree_clean=source_tree_clean
    )
    problems = list(previous["artifact_problems"])
    try:
        actual_browser = browser.read_browser(browser_report, sha)
    except (OSError, ValueError, TypeError, KeyError):
        actual_browser = None
        problems.append("Slice 01.3 browser evidence missing or invalid")
    backend_tests = []
    backend_evidence = []
    for path in junit:
        try:
            artifact = browser.backend.read_junit(path, sha, "real-postgresql")
            backend_tests.extend(artifact.tests)
            backend_evidence.append({"path": artifact.path, "sha256": artifact.sha256})
        except (OSError, ValueError, browser.backend.ET.ParseError):
            problems.append("Slice 01.3 PostgreSQL JUnit missing or invalid")

    def matched(name, module="test_tenancy"):
        return [
            test
            for test in backend_tests
            if test.module.split(".")[-1] == module
            and test.name.split("[", 1)[0] == name
        ]

    guard_status = {
        name: bool(matched(name, "test_tenancy_security"))
        and all(
            test.status == "passed" for test in matched(name, "test_tenancy_security")
        )
        for name in SECURITY_GUARDS
    }
    expected = {
        (name, project)
        for name in browser.BROWSER_NAMES + browser.TENANCY_BROWSER_NAMES
        for project in browser.PROJECTS
    }
    browser_tests = (actual_browser or {}).get("tests", [])
    seen = {(test["name"], test["project"]) for test in browser_tests}
    journeys_passed = expected == seen and all(
        test["status"] == "passed" for test in browser_tests
    )
    evidence = backend_evidence + (
        [{"path": actual_browser["path"], "sha256": actual_browser["sha256"]}]
        if actual_browser
        else []
    )
    observations = [
        {
            "id": result["id"],
            "status": result["status"],
            "source_commit": sha,
            "executed": result["status"] in ("passed", "failed") and not problems,
            "simulated": False,
            "evidence": evidence,
            "reason": "Reconciled Slice 01.2 source-bound PostgreSQL/browser evidence",
        }
        for result in previous["results"]
        if result["id"] in set(browser.backend.MAPPINGS) | set(browser.BROWSER_MAPPINGS)
    ]
    for case_id, (backend_name, browser_name) in REQUIREMENTS.items():
        selected = matched(backend_name)
        selected_browser = [
            test for test in browser_tests if test["name"] == browser_name
        ]
        complete = bool(selected) and {
            test["project"] for test in selected_browser
        } == set(browser.PROJECTS)
        statuses = [test.status for test in selected] + [
            test["status"] for test in selected_browser
        ]
        status = (
            "failed"
            if "failed" in statuses
            else "skipped"
            if "skipped" in statuses
            else "passed"
            if complete
            else "not_run"
        )
        if problems:
            status = "blocked"
        observations.append(
            {
                "id": case_id,
                "status": status,
                "source_commit": sha,
                "executed": complete and not problems,
                "simulated": False,
                "evidence": evidence,
                "reason": "Real PostgreSQL assertion and both real browser viewports",
            }
        )
    report = evaluate(cases, observations, sha)
    applicable = (
        set(browser.backend.MAPPINGS)
        | set(browser.BROWSER_MAPPINGS)
        | set(REQUIREMENTS)
    )
    scope = [result for result in report["results"] if result["id"] in applicable]
    report.update(
        {
            "slice": "01.3",
            "source_tree_clean": source_tree_clean,
            "test_environment": "real-postgresql and real-browser-postgresql",
            "evidence_mode": "offline artifact reconciliation; real-run provenance requires independent verification",
            "artifact_problems": sorted(set(problems)),
            "test_suite": previous["test_suite"],
            "mandatory_session_guards": previous["mandatory_session_guards"],
            "mandatory_tenancy_guards": guard_status,
            "browser_tests": {
                "total": len(browser_tests),
                **{
                    status: sum(test["status"] == status for test in browser_tests)
                    for status in ("passed", "failed", "skipped")
                },
                "all_required_journeys_passed": journeys_passed,
            },
            "slice_evaluations": {
                "applicable": len(scope),
                "ids": sorted(applicable),
                **{
                    status: sum(result["status"] == status for result in scope)
                    for status in ("passed", "failed", "skipped", "blocked", "not_run")
                },
                "eligible": not problems
                and previous["slice_evaluations"]["eligible"]
                and journeys_passed
                and all(guard_status.values())
                and all(result["status"] == "passed" for result in scope),
            },
            "release_ready": False,
            "phase_release_ready": False,
            "instabox": "not assessed",
            "security_review": "not performed by this runner",
        }
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-junit", type=Path, action="append", required=True)
    parser.add_argument("--browser-report", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if head != args.source_commit:
        raise ValueError("Requested source does not match HEAD")
    clean = not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ).strip()
    report = reconcile(
        catalog(root / "evals/cases"),
        args.backend_junit,
        args.browser_report,
        head,
        source_tree_clean=clean,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}))
    return 0 if report["slice_evaluations"]["eligible"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Tenancy evaluation blocked: invalid source or evidence", file=sys.stderr)
        raise SystemExit(1) from None
