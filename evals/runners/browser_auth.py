#!/usr/bin/env python3
"""Offline source-bound acceptance reconciliation, never authenticated merge authority.

Only a trusted harness can establish that supplied XML/JSON came from real execution.
This runner validates metadata and deterministic assertions, not artifact provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import control_plane as backend  # noqa: E402

BROWSER_NAMES = (
    "authenticated project and service journey persists after refresh",
    "incorrect login and validation errors stay safe",
    "cross-user project and service access is denied",
    "logout invalidates the current session",
    "logout all revokes other browser sessions",
    "expired sessions redirect to login",
    "unsafe next redirects stay on this application",
    "keyboard navigation and responsive layout",
)
TENANCY_BROWSER_NAMES = (
    "invited developer gains access and loses it immediately on revocation",
    "viewer can read but cannot mutate project resources",
    "admin manages members without gaining owner authority",
    "project environments stay isolated and archived metadata is immutable",
    "declined and revoked invitations cannot be accepted",
)
PROJECTS = ("desktop", "mobile")
AUTH_MAPPINGS = {
    "EVAL-001": "test_browser_login_and_session_are_authenticated",
    "EVAL-002": "test_browser_rejects_incorrect_credentials",
    "EVAL-015": "test_browser_logout_invalidates_session",
}
GUARDS = {
    "test_browser_login_rate_limit_survives_requests": 1,
    "test_browser_session_expiry_revocation_and_disabled_user": 3,
    "test_browser_mutations_require_origin_and_csrf": 4,
    "test_browser_session_rotation_invalidates_previous_cookie": 1,
    "test_browser_all_sessions_are_revoked": 2,
}
SECURITY_GUARDS = {
    "test_csrf_from_another_session_cannot_authorize_mutation": 1,
    "test_valid_api_bearer_takes_precedence_over_browser_cookie": 1,
    "test_account_without_password_and_wrong_password_have_same_error": 1,
    "test_production_browser_settings_reject_unsafe_configuration": 2,
    "test_secure_cookie_configuration_is_preserved": 1,
}
BROWSER_MAPPINGS = {
    "EVAL-001": BROWSER_NAMES[0],
    "EVAL-002": BROWSER_NAMES[1],
    "EVAL-014": BROWSER_NAMES[0],
    "EVAL-015": BROWSER_NAMES[3],
}


def read_browser(path: Path, sha: str) -> dict:
    if path.stat().st_size > 1024**2:
        raise ValueError("Browser report exceeds size limit")
    raw = path.read_bytes()
    report = json.loads(raw)
    if not isinstance(report, dict) or any(
        (
            type(report.get("schema_version")) is not int,
            report.get("schema_version") != 1,
            report.get("runner_status") != "passed",
            report.get("source_commit") != sha,
            report.get("test_environment") != "real-browser-postgresql",
            report.get("source_tree_clean") is not True,
            report.get("executed") is not True,
            report.get("simulated") is not False,
        )
    ):
        raise ValueError("Browser source or execution metadata mismatch")
    tests = report.get("tests")
    if not isinstance(tests, list) or not tests or len(tests) > 1000:
        raise ValueError("Browser testcase list missing or exceeds limits")
    seen = set()
    for item in tests:
        if not isinstance(item, dict) or set(item) != {
            "name",
            "status",
            "project",
            "viewport",
        }:
            raise ValueError("Browser testcase fields must be sanitized and explicit")
        if item["status"] not in ("passed", "failed", "skipped"):
            raise ValueError("Unknown browser execution status")
        if not isinstance(item["name"], str) or item["name"] not in (
            BROWSER_NAMES + TENANCY_BROWSER_NAMES
        ):
            raise ValueError("Unknown browser scenario")
        if item["project"] not in PROJECTS:
            raise ValueError("Unknown browser project")
        viewport = item["viewport"]
        if (
            not isinstance(viewport, dict)
            or set(viewport) != {"width", "height"}
            or any(
                type(value) is not int or not 240 <= value <= 4096
                for value in viewport.values()
            )
        ):
            raise ValueError("Invalid browser viewport")
        if (item["project"] == "mobile") != (viewport["width"] < 768):
            raise ValueError("Browser viewport does not match project")
        key = (item["name"], item["project"])
        if key in seen:
            raise ValueError("Duplicate browser testcase identity")
        seen.add(key)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "tests": tests,
    }


def reconcile(cases, junit, browser_report, sha, *, source_tree_clean):
    base = backend.reconcile(
        cases,
        junit,
        sha,
        environment="real-postgresql",
        source_tree_clean=source_tree_clean,
    )
    problems = list(base["artifact_problems"])
    browser = None
    try:
        browser = read_browser(browser_report, sha)
    except (OSError, ValueError, TypeError, KeyError):
        problems.append(
            "Browser evidence missing, malformed, stale, simulated or unsanitized"
        )
    tests = []
    for path in junit:
        try:
            tests.extend(backend.read_junit(path, sha, "real-postgresql").tests)
        except (OSError, ValueError, backend.ET.ParseError):
            pass  # The base reconciler already records unreadable evidence.
    observations = []
    for result in base["results"]:
        if result["id"] in backend.MAPPINGS:
            observations.append(
                {
                    **result,
                    "source_commit": sha,
                    "executed": result["status"] in ("passed", "failed"),
                    "simulated": False,
                    "evidence": base["artifacts"],
                }
            )
    applicable = set(backend.MAPPINGS) | set(BROWSER_MAPPINGS)
    for case_id in BROWSER_MAPPINGS:
        selected = [
            item
            for item in (browser or {}).get("tests", [])
            if item["name"] == BROWSER_MAPPINGS[case_id]
        ]
        statuses = [item["status"] for item in selected]
        complete = {item["project"] for item in selected} == set(PROJECTS)
        if case_id in AUTH_MAPPINGS:
            matching = [
                item
                for item in tests
                if item.module.split(".")[-1] == "test_browser_auth"
                and item.name.split("[", 1)[0] == AUTH_MAPPINGS[case_id]
            ]
            statuses.extend(item.status for item in matching)
            complete = complete and bool(matching)
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
                "evidence": base["artifacts"]
                + (
                    [{"path": browser["path"], "sha256": browser["sha256"]}]
                    if browser
                    else []
                ),
                "reason": "Provisioned-account login, not public registration"
                if case_id == "EVAL-001"
                else "Source-bound backend assertions and desktop/mobile browser journey",
            }
        )
    browser_tests = (browser or {}).get("tests", [])
    expected = {(name, project) for name in BROWSER_NAMES for project in PROJECTS}
    observed = {(item["name"], item["project"]) for item in browser_tests}
    browser_complete = expected.issubset(observed) and all(
        item["status"] == "passed" for item in browser_tests
    )
    guard_results = {}
    for name, minimum in (GUARDS | SECURITY_GUARDS).items():
        module = (
            "test_browser_security" if name in SECURITY_GUARDS else "test_browser_auth"
        )
        selected = [
            item
            for item in tests
            if item.module.split(".")[-1] == module
            and item.name.split("[", 1)[0] == name
        ]
        guard_results[name] = len(selected) >= minimum and all(
            item.status == "passed" for item in selected
        )
    report = backend.evaluate(cases, observations, sha)
    scope = [item for item in report["results"] if item["id"] in applicable]
    report.update(
        {
            "slice": "01.2",
            "source_tree_clean": source_tree_clean,
            "test_environment": "real-postgresql and real-browser-postgresql",
            "evidence_mode": "offline artifact reconciliation; trusted harness provenance requires independent verification",
            "artifact_problems": sorted(set(problems)),
            "test_suite": base["test_suite"],
            "mandatory_session_guards": guard_results,
            "browser_tests": {
                "total": len(browser_tests),
                **{
                    status: sum(item["status"] == status for item in browser_tests)
                    for status in ("passed", "failed", "skipped")
                },
                "all_required_journeys_passed": browser_complete,
            },
            "slice_evaluations": {
                "applicable": len(scope),
                "ids": sorted(applicable),
                **{
                    status: sum(item["status"] == status for item in scope)
                    for status in ("passed", "failed", "skipped", "blocked", "not_run")
                },
                "eligible": not problems
                and base["slice_evaluations"]["eligible"]
                and browser_complete
                and all(guard_results.values())
                and all(item["status"] == "passed" for item in scope),
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
        backend.catalog(root / "evals/cases"),
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
        print(
            "Browser authentication evaluation blocked: invalid source or evidence",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
