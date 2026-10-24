"""One-time, additive main protection configuration using an authorized gh session."""

import argparse
from copy import deepcopy
import json
import subprocess

BASE = "repos/ralphdeeney/lava"
RULESET = f"{BASE}/rulesets/25796131"
REQUIRED = ("engineering-controls", "checks")
APP_ID = 15368  # GitHub Actions, observed on this repository's verified checks.
FIELDS = ("name", "target", "enforcement", "conditions", "rules", "bypass_actors")


def api(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    command = ["gh", "api", "--method", method, path]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        # Never echo arbitrary API output or CLI diagnostics from credentialed calls.
        try:
            status = json.loads(result.stdout).get("status", "unavailable")
        except ValueError:
            status = "unavailable"
        raise RuntimeError(
            f"GitHub {method} failed (status {status}); no retry attempted. "
            "Use an authorized gh session with repository Administration read/write."
        )
    return json.loads(result.stdout)


def writable(snapshot: dict) -> dict:
    return {key: deepcopy(snapshot[key]) for key in FIELDS}


def proposal(snapshot: dict, default_branch: str) -> dict:
    result = writable(snapshot)
    if result["target"] != "branch" or result["enforcement"] != "active":
        raise ValueError("Expected an active branch ruleset; refusing changes.")
    refs = result["conditions"].get("ref_name", {})
    includes = refs.get("include", [])
    if refs.get("exclude") or not (
        "refs/heads/main" in includes
        or (default_branch == "main" and "~DEFAULT_BRANCH" in includes)
    ):
        raise ValueError(
            "Cannot establish that ruleset covers main without exclusions."
        )
    if result["bypass_actors"]:
        raise ValueError("Bypass actors require independent review; refusing changes.")
    types = {rule["type"] for rule in result["rules"]}
    if not {"deletion", "non_fast_forward", "pull_request"} <= types:
        raise ValueError("Existing baseline protections are missing; refusing changes.")
    status = [r for r in result["rules"] if r["type"] == "required_status_checks"]
    if len(status) > 1:
        raise ValueError("Ambiguous status-check rules; refusing changes.")
    if not status:
        status = [{"type": "required_status_checks", "parameters": {}}]
        result["rules"].extend(status)
    parameters = status[0]["parameters"]
    parameters["strict_required_status_checks_policy"] = True
    parameters["do_not_enforce_on_create"] = False
    checks = parameters.setdefault("required_status_checks", [])
    for context in REQUIRED:
        if not any(
            c["context"] == context and c.get("integration_id") == APP_ID
            for c in checks
        ):
            checks.append({"context": context, "integration_id": APP_ID})
    return result


def configure(apply: bool) -> None:
    repo = api(BASE)
    snapshot = api(RULESET)
    desired = proposal(snapshot, repo["default_branch"])
    if not apply:
        print(json.dumps({"mode": "preview", "proposed_ruleset": desired}, indent=2))
        return
    # Fail on observed concurrent edits; admins must serialize configuration changes.
    if writable(api(RULESET)) != writable(snapshot):
        raise RuntimeError(
            "Ruleset changed during configuration; stopped without writing."
        )
    if writable(snapshot) != desired:
        api(RULESET, "PUT", desired)
    if writable(api(RULESET)) != desired:
        raise RuntimeError("Ruleset read-back mismatch; auto-merge settings untouched.")
    # Only enable repository settings after protection has been verified.
    if not (repo["allow_auto_merge"] and repo["allow_squash_merge"]):
        api(BASE, "PATCH", {"allow_auto_merge": True, "allow_squash_merge": True})
    final_repo = api(BASE)
    if not (final_repo["allow_auto_merge"] and final_repo["allow_squash_merge"]):
        raise RuntimeError("Repository auto-merge settings were not verified.")
    if writable(api(RULESET)) != desired:
        raise RuntimeError("Final protection read-back mismatch; stop before PR merge.")
    print(
        json.dumps(
            {
                "protection_verified": True,
                "required_checks": list(REQUIRED),
                "squash_auto_merge_available": True,
                "pr_auto_merge_enabled_by_script": False,
            }
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Apply and read back policy"
    )
    args = parser.parse_args()
    try:
        configure(args.apply)
    except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(f"Configuration stopped: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
