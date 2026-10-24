"""Durable one-repair state machine and fail-closed release evidence checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import fcntl
import json
import os
from pathlib import Path
import re
from typing import Any


class PolicyError(ValueError):
    pass


@dataclass
class Slice:
    phase: str
    slice_id: str
    branch: str
    source_commit: str
    state: str = "IMPLEMENT"
    repair_attempts: int = 0
    diagnosis: str | None = None
    pr_url: str | None = None
    merged_commit: str | None = None
    blockers: list[str] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", self.source_commit):
            raise PolicyError("An exact source commit is required")
        if self.repair_attempts not in (0, 1):
            raise PolicyError("At most one repair is permitted")

    def verification(self, results: list[dict], *, source_commit: str) -> None:
        self.validate()
        if source_commit != self.source_commit:
            raise PolicyError("Verification is for a different commit")
        if self.state not in ("IMPLEMENT", "REPAIR"):
            raise PolicyError(
                "Initial verification or the single retest was already recorded"
            )
        if not results or len({result["name"] for result in results}) != len(results):
            raise PolicyError("Collect a nonempty, uniquely named aggregate result set")
        for result in results:
            if result.get("status") not in ("passed", "failed", "blocked", "not_run"):
                raise PolicyError("Unknown result status")
            if result.get("status") == "passed" and (
                result.get("executed") is not True
                or result.get("simulated") is not False
            ):
                raise PolicyError("Unexecuted checks cannot pass")
        passed = all(result["status"] == "passed" for result in results)
        self.runs.append(
            {
                "source_commit": source_commit,
                "results": results,
                "kind": "retest" if self.state == "REPAIR" else "initial",
            }
        )
        self.state = (
            "VERIFIED"
            if passed
            else ("BLOCKED" if self.state == "REPAIR" else "DIAGNOSE")
        )

    def repair(self, diagnosis: str, new_commit: str) -> None:
        if (
            self.state != "DIAGNOSE"
            or self.repair_attempts != 0
            or not diagnosis.strip()
        ):
            raise PolicyError(
                "A failed aggregate, diagnosis and unused repair budget are required"
            )
        if (
            not re.fullmatch(r"[0-9a-f]{40}", new_commit)
            or new_commit == self.source_commit
        ):
            raise PolicyError("Repair must identify its new exact commit")
        self.diagnosis = diagnosis
        self.repair_attempts = 1
        self.source_commit = new_commit
        self.state = "REPAIR"

    def open_pr(self, url: str) -> None:
        if self.state != "VERIFIED" or not re.fullmatch(
            r"https://github.com/ralphdeeney/lava/pull/\d+", url
        ):
            raise PolicyError("Verified implementation and repository PR URL required")
        self.pr_url = url
        self.state = "PR_OPEN"

    def confirm_merge(self, observed: dict) -> None:
        if self.state != "AUTOMERGE_ENABLED" or observed.get("merged") is not True:
            raise PolicyError("Enablement is not evidence of a completed merge")
        if observed.get("head_sha") != self.source_commit or not re.fullmatch(
            r"[0-9a-f]{40}", observed.get("merge_commit", "")
        ):
            raise PolicyError(
                "Merge evidence must identify this head and a real merge commit"
            )
        self.merged_commit = observed["merge_commit"]
        self.state = "MERGED"


def assess_merge(policy: dict, evidence: dict, sha: str) -> list[str]:
    """Unknown/missing observations are blockers, never implied successful gates."""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return ["Invalid full source commit SHA"]
    blockers = []
    if policy.get("protection_verified") is not True:
        blockers.append("main protection is unavailable or unverified")
    if policy.get("enforce_admins") is not True or policy.get("bypass_actors") != []:
        blockers.append("administrator enforcement/no-bypass policy is not verified")
    if (
        policy.get("auto_merge_enabled") is not True
        or policy.get("squash_enabled") is not True
    ):
        blockers.append("protected squash auto-merge is not enabled")
    required = policy.get("required_checks")
    if not required:
        blockers.append("required check names have not been discovered/configured")
    observed = evidence.get("checks", {})
    for name in required or []:
        check = observed.get(name, {})
        if check.get("source_commit") != sha or check.get("conclusion") != "success":
            blockers.append(f"required check not successful for exact head: {name}")
    if (
        evidence.get("source_commit") != sha
        or evidence.get("scope_authorized") is not True
    ):
        blockers.append("exact-head authorized scope is unverified")
    if (
        evidence.get("mergeable") is not True
        or evidence.get("approvals_satisfied") is not True
    ):
        blockers.append("GitHub mergeability/approval rules are not satisfied")
    security = evidence.get("security", {})
    if (
        security.get("independent") is not True
        or security.get("critical_findings") != 0
        or security.get("source_commit") != sha
        or security.get("executed") is not True
        or security.get("simulated") is not False
    ):
        blockers.append("independent security review is missing or blocking")
    evaluations = evidence.get("evals", {})
    if (
        evaluations.get("executed") is not True
        or evaluations.get("source_commit") != sha
        or evaluations.get("simulated") is not False
        or evaluations.get("mandatory_total", 0) < 20
        or evaluations.get("passed") != evaluations.get("mandatory_total")
        or evaluations.get("failed") != 0
        or evaluations.get("skipped") != 0
    ):
        blockers.append("mandatory deterministic evaluations are incomplete")
    vm = evidence.get("instabox", {})
    if (
        vm.get("executed") is not True
        or vm.get("simulated") is not False
        or vm.get("status") != "succeeded"
        or vm.get("source_commit") != sha
        or vm.get("exitCode") != 0
    ):
        blockers.append("real exact-head InstaBox execution has not passed")
    return blockers


class Store:
    """Lock + atomic replace; rejected mutations leave the previous record intact."""

    def __init__(self, path: Path):
        self.path = path

    def update(self, mutate) -> Slice:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = Slice(**json.loads(self.path.read_text()))
            value.validate()
            mutate(value)
            value.validate()
            temporary = self.path.with_suffix(".tmp")
            with os.fdopen(
                os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "w"
            ) as file:
                json.dump(asdict(value), file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
            return value
