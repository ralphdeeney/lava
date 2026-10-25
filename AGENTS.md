# Working on LAVA

Use the existing checkout; cloud tasks are isolated. Do not create worktrees unless requested.
Read ARCHITECTURE.md, DEVELOPMENT.md, SECURITY.md and the current verification evidence first.
The modular monolith lives in apps/api/src/lava; the dashboard lives in apps/web.

## Delivery discipline

- Work in small, reviewable implementation slices with a concrete acceptance check.
- Run automated unit and integration tests appropriate to each slice. Run scripts/check.sh
  after relevant edits; database/container changes also require real PostgreSQL tests and the
  disposable Compose gate. Keep passed, failed, skipped, mocked and unexecuted checks distinct.
- Diagnose ordinary failures and attempt safe, bounded recovery autonomously. Retry only after
  identifying a transient condition or making a supported correction; never disable safety
  checks, integrity verification, assertions or tests to force a pass.
- Push authorized feature-branch changes and inspect GitHub Actions for the exact commit.
  Fix ordinary CI errors before claiming completion. Never merge without explicit authorization.
- Report actual commands, outcomes, exact SHAs and workflow links. Distinguish operator-reported
  evidence from agent-executed results; never describe mocks as real infrastructure verification.

## Infrastructure and security

- Use uv/pnpm with committed locks, pinned images and reproducible bootstrap scripts.
- Never hardcode or print credentials, dump environments, commit .env, or retain raw secret-bearing
  diagnostics. Use GitHub Actions secrets for remote orchestration and scoped temporary credentials.
- Keep Docker operations outside the API. Never expose PostgreSQL or Docker APIs publicly.
- Remote tests must select the exact intended commit, serialize access to the shared VM, respect
  lifecycle/time/rate limits, preserve persistent resources and avoid changing daemon storage.
- Use a unique disposable Compose project; cleanup only resources owned by that run. Never use
  global prune, reset an operator checkout, delete persistent VM data, or create paid resources.
- Recover by stopping the owned failed run and retaining bounded sanitized evidence. Preserve the
  previous known-good commit; roll back only the run's disposable checkout/resources. Do not
  deploy an older application schema or modify persistent databases automatically.
- Escalate only concrete external authorization/account restrictions, security-sensitive changes,
  irreversible operations or unresolved evidence after safe recovery. Do not ask operators to
  perform routine tests, package installation or interactive SSH during normal automation.

## Phase boundaries

Phase 00 PR #1 is merged at 284547ce6fc7ae69f5633262831981c25fefcd8c.
Phase 01 scope is control-plane metadata/auth/dashboard only; no customer-container execution.
Configure and verify protected auto-merge policy before starting product slices. Unknown or
unavailable main protection is a blocker, never permission for a direct merge workaround.
Use the six specialist instructions under .agents/; implementation cannot approve its own
security findings. Collect all initial failures, diagnose once, make one bounded repair, and
retest once. A remaining failure permanently blocks dependent slices. Track exact SHA, repair
count, tests/evals, PR and actual merge state; never advance on auto-merge enablement alone.
No persistent coding runner is currently verified: do not claim autonomous background work.
Do not run unreviewed candidate code on a credential-bearing or Docker-root persistent VM.
The existing Phase 00 VM workflow is evidence for its trusted sources, not a security gate
for arbitrary Phase 01 PRs. Slice01.1 passed9 applicable evaluations;11 broader scenarios remained outstanding at its
checkpoint. Later scores require independently executed exact-source evidence. See engineering/README.md and evals/README.md.
No Kubernetes, billing, autoscaling or AI agents in these phases.
