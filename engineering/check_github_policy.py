#!/usr/bin/env python3
"""Read actual policy metadata; never mutate settings or merge a PR."""

import argparse
import json
from pathlib import Path
import subprocess


def get(path: str) -> tuple[dict | list | None, str | None]:
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if result.returncode:
        try:
            message = json.loads(result.stdout).get("message", "API unavailable")
        except ValueError:
            message = "API unavailable"
        return None, message
    return json.loads(result.stdout), None


parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
base = "repos/ralphdeeney/lava"
repo, repo_error = get(base)
branch, branch_error = get(base + "/branches/main")
protection, protection_error = get(base + "/branches/main/protection")
rules, rules_error = get(base + "/rulesets")
report = {
    "repository": "ralphdeeney/lava",
    "private": (repo or {}).get("private"),
    "auto_merge_enabled": (repo or {}).get("allow_auto_merge"),
    "main_protected": (branch or {}).get("protected"),
    "protection_verified": protection is not None,
    "errors": {
        "repository": repo_error,
        "branch": branch_error,
        "protection": protection_error,
        "rulesets": rules_error,
    },
    "protected_automerge_ready": False,
    "metadata_only": True,
    "blockers": [
        "Read-only metadata probe: no verified protected merge controller is active"
    ],
}

args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
raise SystemExit(0 if report["protected_automerge_ready"] else 1)
