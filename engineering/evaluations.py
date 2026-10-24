"""Catalog/result reconciliation: missing, simulated and stale evidence cannot pass."""

from __future__ import annotations

import json
import re
from pathlib import Path


def catalog(root: Path) -> list[dict]:
    # JSON is an intentionally restricted, safe YAML subset; no executable YAML tags.
    cases = [
        case
        for path in sorted(root.glob("*.yaml"))
        for case in json.loads(path.read_text())
    ]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)) or not cases:
        raise ValueError("Evaluation IDs must be unique and nonempty")
    return cases


def evaluate(cases: list[dict], observations: list[dict], sha: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("An exact full source commit SHA is required")
    ids = [case["id"] for case in cases]
    required = {f"EVAL-{index:03}" for index in range(1, 21)}
    if not ids or len(ids) != len(set(ids)) or not required.issubset(ids):
        raise ValueError("The complete, unique Phase 01 mandatory catalog is required")
    indexed = {}
    for observation in observations:
        case_id = observation["id"]
        if case_id in indexed:
            raise ValueError("Duplicate observations are ambiguous")
        indexed[case_id] = observation
    results = []
    for case in cases:
        observed = indexed.get(case["id"], {})
        status = observed.get("status", "not_run")
        valid = (
            observed.get("source_commit") == sha
            and observed.get("executed") is True
            and observed.get("simulated") is False
            and observed.get("evidence")
        )
        if status == "passed" and not valid:
            status = "blocked"
        if status not in ("passed", "failed", "skipped", "blocked", "not_run"):
            raise ValueError("Unknown evaluation status")
        results.append(
            {
                "id": case["id"],
                "status": status,
                "reason": observed.get("reason")
                or (
                    "Executed acceptance evidence"
                    if status == "passed"
                    else "No executed acceptance evidence"
                ),
                "critical": case.get("critical", False),
            }
        )
    counts = {
        name: sum(result["status"] == name for result in results)
        for name in ("passed", "failed", "skipped", "blocked", "not_run")
    }
    critical = sum(
        result["critical"] and result["status"] == "failed" for result in results
    )
    return {
        "project": "LAVA",
        "phase": "01",
        "source_commit": sha,
        "mandatory_total": len(cases),
        **counts,
        "critical_security_failures": critical,
        "results": results,
        "release_ready": counts["passed"] == len(cases) and critical == 0,
    }
