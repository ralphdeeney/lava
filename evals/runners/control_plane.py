#!/usr/bin/env python3
"""Reconcile independently executed Slice 01.1 JUnit; never grade mocked browser/VM work.

This offline runner checks artifact metadata, not cryptographic provenance. A protected,
trusted coordinator must generate the source-bound JUnit from real PostgreSQL execution.
Caller-provided XML or environment labels alone are not authenticated merge evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engineering.evaluations import catalog, evaluate  # noqa: E402


@dataclass(frozen=True)
class Requirement:
    module: str
    name: str
    minimum: int = 1


# Only real acceptance assertions for this slice are eligible. No registration,
# cookie-session, environment, deployment, browser, HTTP outage or cleanup claims.
MAPPINGS: dict[str, tuple[Requirement, ...]] = {
    "EVAL-003": (
        Requirement(
            "test_control_plane_security", "test_unauthenticated_projects_are_denied"
        ),
    ),
    "EVAL-005": (
        Requirement(
            "test_control_plane_security", "test_other_user_cannot_access_project"
        ),
    ),
    "EVAL-006": (
        Requirement(
            "test_control_plane_security", "test_other_user_cannot_modify_service"
        ),
    ),
    "EVAL-016": (
        Requirement(
            "test_control_plane_security",
            "test_unauthorized_errors_do_not_enumerate_resources",
        ),
    ),
    "EVAL-017": (
        Requirement(
            "test_control_plane_security",
            "test_errors_and_logs_do_not_disclose_bearer_or_database_credentials",
        ),
    ),
    "EVAL-004": (
        Requirement(
            "test_control_plane", "test_project_create_retrieve_update_and_owned_list"
        ),
    ),
    "EVAL-009": (
        Requirement(
            "test_control_plane",
            "test_invalid_service_configuration_is_rejected",
            minimum=9,
        ),
    ),
    "EVAL-012": (
        Requirement(
            "test_control_plane",
            "test_project_and_service_survive_real_api_process_restart",
        ),
    ),
    "EVAL-013": (
        Requirement("test_database", "test_migration_round_trip"),
        Requirement(
            "test_database", "test_legacy_project_is_preserved_by_owner_migration"
        ),
    ),
}


@dataclass(frozen=True)
class TestResult:
    module: str
    name: str
    status: str


@dataclass
class Artifact:
    path: str
    sha256: str
    tests: list[TestResult]
    problems: list[str]


def read_junit(path: Path, sha: str, environment: str) -> Artifact:
    if path.stat().st_size > 8 * 1024**2:
        raise ValueError("JUnit exceeds the 8 MiB report limit")
    raw = path.read_bytes()
    document = ET.fromstring(raw)
    suites = (
        [document]
        if document.tag == "testsuite"
        else list(document.findall(".//testsuite"))
    )
    problems = []
    tests = []
    if not suites:
        problems.append("JUnit contains no test suites")
    for suite in suites:
        properties: dict[str, str] = {}
        for item in suite.findall("./properties/property"):
            key, value = item.get("name", ""), item.get("value", "")
            if key in properties:
                problems.append("Duplicate JUnit metadata property")
            properties[key] = value
        if properties.get("source_commit") != sha:
            problems.append("JUnit source_commit does not match the exact source SHA")
        if properties.get("test_environment") != environment:
            problems.append(
                "JUnit does not declare the real PostgreSQL test environment"
            )
        for testcase in suite.findall("./testcase"):
            if len(tests) >= 10000:
                raise ValueError("JUnit exceeds the testcase limit")
            status = "passed"
            if (
                testcase.find("failure") is not None
                or testcase.find("error") is not None
            ):
                status = "failed"
            elif testcase.find("skipped") is not None:
                status = "skipped"
            tests.append(
                TestResult(
                    testcase.get("classname", ""), testcase.get("name", ""), status
                )
            )
    if not tests:
        problems.append("JUnit contains zero executed/collected testcases")
    return Artifact(
        str(path), hashlib.sha256(raw).hexdigest(), tests, sorted(set(problems))
    )


def reconcile(
    cases: list[dict],
    junit: list[Path],
    sha: str,
    *,
    environment: str,
    source_tree_clean: bool,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("An exact full source commit is required")
    if environment != "real-postgresql":
        raise ValueError("Slice acceptance requires real-postgresql execution")
    artifacts = []
    problems = []
    if not source_tree_clean:
        problems.append(
            "Working tree is dirty; current source is not attributable to HEAD"
        )
    if not junit:
        problems.append("No JUnit execution evidence supplied")
    all_tests: list[TestResult] = []
    for path in junit:
        try:
            artifact = read_junit(path, sha, environment)
        except (OSError, ValueError, ET.ParseError):
            problems.append("JUnit evidence is unreadable, malformed or exceeds limits")
            continue
        artifacts.append(
            {
                "path": artifact.path,
                "sha256": artifact.sha256,
                "metadata_verified": not artifact.problems,
                "testcases": len(artifact.tests),
            }
        )
        problems.extend(artifact.problems)
        all_tests.extend(artifact.tests)
    keys = [(test.module, test.name) for test in all_tests]
    if len(keys) != len(set(keys)):
        problems.append("Duplicate testcase identities across supplied JUnit artifacts")
    suite_counts = {
        "total": len(all_tests),
        **{
            status: sum(test.status == status for test in all_tests)
            for status in ("passed", "failed", "skipped")
        },
    }
    observations = []
    for case_id, requirements in MAPPINGS.items():
        status, reasons, matched = "passed", [], []
        for requirement in requirements:
            selected = [
                test
                for test in all_tests
                if test.module.split(".")[-1] == requirement.module
                and test.name.split("[", 1)[0] == requirement.name
            ]
            matched.extend(f"{test.module}::{test.name}" for test in selected)
            if len(selected) < requirement.minimum:
                reasons.append(
                    f"Missing required test: {requirement.module}::{requirement.name}"
                )
                if status != "failed":
                    status = "not_run"
            if any(test.status == "failed" for test in selected):
                status = "failed"
                reasons.append("A mapped testcase failed")
            elif any(test.status == "skipped" for test in selected) and status not in (
                "failed",
                "not_run",
            ):
                status = "skipped"
                reasons.append("A mapped testcase was skipped")
        if problems:
            status = "blocked"
            reasons.extend(sorted(set(problems)))
        observations.append(
            {
                "id": case_id,
                "source_commit": sha,
                "status": status,
                "executed": status in ("passed", "failed")
                and bool(matched)
                and not problems,
                "simulated": False,
                "evidence": artifacts,
                "reason": "; ".join(sorted(set(reasons)))
                or "All mapped real-PostgreSQL testcases executed and passed",
            }
        )
    report = evaluate(cases, observations, sha)
    applicable = [item for item in report["results"] if item["id"] in MAPPINGS]
    report.update(
        {
            "slice": "01.1",
            "test_environment": environment,
            "source_tree_clean": source_tree_clean,
            "evidence_mode": "offline JUnit reconciliation; runner provenance requires independent verification",
            "artifact_problems": sorted(set(problems)),
            "artifacts": artifacts,
            "test_suite": suite_counts,
            "slice_evaluations": {
                "applicable": len(applicable),
                "ids": sorted(MAPPINGS),
                "passed": sum(item["status"] == "passed" for item in applicable),
                "failed": sum(item["status"] == "failed" for item in applicable),
                "skipped": sum(item["status"] == "skipped" for item in applicable),
                "blocked": sum(item["status"] == "blocked" for item in applicable),
                "not_run": sum(item["status"] == "not_run" for item in applicable),
                "eligible": not problems
                and bool(applicable)
                and suite_counts["failed"] == 0
                and suite_counts["skipped"] == 0
                and all(item["status"] == "passed" for item in applicable),
            },
            "security_review": "not performed by this runner",
            "browser_tests": "not_run",
            "instabox": "not assessed by this runner",
        }
    )
    # Unsupported Phase 01 features remain not_run. Slice eligibility never means phase release.
    report["phase_release_ready"] = report["release_ready"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, action="append", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--environment", choices=["real-postgresql"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if args.source_commit != head:
        raise ValueError("Requested source commit does not match checked-out HEAD")
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        ).strip()
    )
    report = reconcile(
        catalog(root / "evals/cases"),
        args.junit,
        head,
        environment=args.environment,
        source_tree_clean=not dirty,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in ("results", "artifacts")
            }
        )
    )
    return 0 if report["slice_evaluations"]["eligible"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            f"Control-plane evaluation blocked: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
