# Autonomous development control interfaces

`control.py` implements durable one-repair accounting and fail-closed evidence assessment.
`Slice.verification` records the entire initial failure set before repair. One diagnosis and
one changed commit consume the only repair; failed retest is terminal BLOCKED. Aggregate
initial results must be collected before recording the run. Transport retries are separate
and may not replay uncertain non-idempotent infrastructure calls.

`Store` serializes local updates under flock and atomically replaces its JSON record. It is a
local durable state interface, not tamperproof storage or an authenticated remote evidence
store. Git history retains reviewed milestones. Never reset its repair budget for a failed
slice. After MERGED, a coordinator may create the next authorized slice; auto-merge enablement
alone must never advance the roadmap.

No persistent coding-agent runner is provisioned or verified. Native Codex specialists were
invoked in this task; future coding work needs a new authorized Codex task or an independently
secured persistent runner. GitHub Actions only runs submitted code; it does not autonomously
implement the next slice. No background coding, protected-main controller or automatic merge
is claimed active.

Current blocker after owner configuration: main has active ruleset25796131 and native
repository auto-merge is enabled. However, the ruleset's required_status_checks list is
empty and strict_required_status_checks_policy is false. CI is not enforced. There are
no bypass actors, but this does not compensate for absent required checks. Supported
REST PUT of the prepared baseline to this existing ruleset returned403, Resource not
accessible by integration. PR2 is ready for review; PR auto-merge remains withheld.
An Administration read/write-capable connection or owner settings change is still required.
Do not merge around this gap. The prepared existing-check payload is only a baseline;
Phase01 needs independently verified security/browser/evaluation and trusted integration gates.

A privileged controller must run from protected main/pinned trusted code, never from the PR
checkout while holding infrastructure credentials. Candidate VM tests require independent
review and separation from operator credentials/persistent resources. Current Phase 00
remote verification remains restricted to its trusted sources and is not a Phase 01 security
gate. Security findings in the progress report are blockers until remedied and independently
verified. No API/merge adapter is enabled while these trust prerequisites are unresolved.

## Recorded attempt

Phase 00 was already merged when this task began. The initial control-interface run collected
18 failures/98 passes plus two additional review regression failures before any repair. One
failure was a test-harness migration working-directory error, not an application defect.
A single aggregate repair addressed the complete failure set and formatter findings. The only
post-repair full run passed118 tests, plus the separate repeat PostgreSQL migration check.
No second code repair was attempted. Independent static security retest found no remaining
blocking defect in the offline interfaces; it did not approve privileged Phase01 execution.

`state/interface-checkpoint.json` retains the initial aggregate, diagnosis, repair counter and
single retest against the exact repaired code commit. `state/progress.json` records the phase,
branch, checkpoint SHA, tests, unexecuted acceptance/browser/VM work and external blockers.
Because a tracked file cannot contain its own Git SHA, checkpoint_source_commit is the tested
implementation checkpoint; GitHub workflow artifacts and the PR record the final submission
SHA. This distinction prevents stale source claims.

`main-protection.proposed.json` is a reviewable baseline using actual observed Phase00 check
names (`checks`, `integration`, GitHub Actions app15368), strict status updates, administrator
enforcement, linear history and no force push/deletion. The PUT attempt failed403; this file
is not applied configuration and is insufficient for Phase01 without subsequently executed
security/browser/evaluation checks and a trusted controller. Auto-merge was not enabled.


## Public-repository resumption

`state/policy-observation.json` records the new public-repository observations and the denied
REST/GraphQL administration attempts. The former private-plan observation is retained in
`state/policy-observation-before-public.json` as historical evidence. `viewerCanAdminister=true`
and repo permissions.admin=true report the user's role; they do not grant missing GitHub
integration permissions. The only available credential is the existing GH_TOKEN connection;
no alternate administrator identity was found, and no credential was printed or extracted.

`main-ruleset.proposed.json` is a supported REST alternative to branch protection; it has no
bypass actors and binds known check contexts to the GitHub Actions app. The existing-check
proposals are fail-closed baselines, not completed Phase01 security policy. A relevant exact-head
integration check is still necessary for PR2; historical main checks cannot satisfy it.
Actual security/browser/evaluation checks must be implemented, executed and discovered before
being required. Never fabricate successful check names or authorize a candidate's self-report.

`native-auto-merge.proposed.json` is the supported repository-settings payload for native
squash auto-merge. It was deliberately not applied while protection could not be verified.
The owner can approve an Administration read/write-capable GitHub connection, or use GitHub
Settings to install the policy and enable squash auto-merge. Neither action requires sharing
credentials in chat. Future ordinary tests still use Actions/API automation without SSH;
this exceptional repository-authorization step cannot be supplied by application code.

## One-time authorized GitHub CLI setup

Run from this checkout in a secure environment whose existing `gh` session has repository
Administration read/write. No token argument, credential copy, interactive SSH or Actions
infrastructure secret is required. Do not run concurrent ruleset edits while applying.

```sh
./scripts/configure-github-protection.sh          # read-only proposed configuration
./scripts/configure-github-protection.sh --apply  # apply once and verify live read-back
```

The script targets existing ruleset25796131 for ralphdeeney/lava. It preserves its name,
conditions, rules, PR requirements and existing status checks, refuses inactive/ambiguous
main coverage or bypass actors, adds the verified `engineering-controls` and `checks`
contexts pinned to GitHub Actions app15368, and enables strict updates. It detects observed
concurrent edits before writing. GitHub does not provide atomic compare-and-swap for this
operation; administrators must serialize settings changes. Live read-back must exactly match
the proposed writable policy before enabling native repository auto-merge/squash availability.
It does not enable any PR's auto-merge, merge a PR, change other merge methods, weaken a rule,
access InstaBox or retry mutations. A later settings failure leaves stronger protection in
place and requires inspection, rather than automatic rollback.

The Codex session's single apply attempt returned403 on the ruleset PUT; no changes occurred.
Use the same script in an already authorized owner CLI session, or grant an approved connection
Administration access. Do not send credentials in chat. After success, verify exact-head PR
checks and independent security findings before enabling PR auto-merge with the verified SHA:

```sh
gh pr merge 2 --auto --squash --match-head-commit <verified-head-sha>
```

Replace the placeholder; never use `--admin`.
These two baseline checks are not the unimplemented Phase01 product/browser/VM acceptance gates.
