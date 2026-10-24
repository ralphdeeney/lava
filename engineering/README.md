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

Current blocker: main is unprotected; branch-protection read/write returns403, and private-repo
rulesets return the GitHub Pro/public visibility restriction. Auto-merge remains disabled.
Do not use a direct merge script, make the repository public, purchase a plan, or merge any
Phase 01 slice to work around this restriction. The prepared existing-check protection payload
is only an initial baseline; actual executed Phase 01 security/browser/eval check names must
be discovered and required before those slices can qualify.

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
