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

Phase 00 includes foundation and its release/infrastructure verification only. Phase 01 tasks
may be planned in ROADMAP.md but implementation must wait until Phase 00 is merged.
No Kubernetes, billing, autoscaling or AI agents in these phases.
