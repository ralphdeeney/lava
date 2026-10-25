# Roadmap

## Historical Phase00 release plan (completed)

Require frozen dependency installation, frontend checks/build, complete backend tests, real
PostgreSQL migration round trips, disposable Compose functional checks, and GitHub Actions
success for the exact PR head. The operator reports the manual agent-development gate passed;
remote Actions-to-InstaBox automation must independently reproduce it before the new automation
is declared verified. Retain sanitized evidence and serialize all shared-machine runs.

Do not merge automatically. Phase 01 remains blocked until Phase 00 is merged into main.

## Historical deployment-engine plan (superseded)

1. Define deployment IDs, immutable source/image identity, state transitions, failure reasons,
   idempotency and retry/cancellation contracts. Test transition invariants and recovery rules.
2. Add project/application persistence and application services inside the modular monolith.
   Introduce reversible migrations and test ownership/validation boundaries before public APIs.
3. Implement a durable deployment queue and a separate least-privilege worker. Test duplicate
   jobs, interrupted claims, bounded retries and recovery after worker restart.
4. Implement the Railpack + BuildKit BuildEngine adapter in an isolated build environment.
   Verify build provenance, resource limits, cache ownership and sanitized logs with a fixture app.
5. Implement the Docker ContainerRuntime adapter in the worker. Test digest-pinned starts,
   health transitions, timeouts and cleanup of only deployment-owned resources.
6. Implement Traefik Networking with validated hostnames and private upstreams. Test route
   publication/withdrawal and prevent routing privileged/internal services.
7. Join the adapters into one deployment vertical slice on disposable infrastructure. Prove
   failure recovery and safe rollback before expanding the platform. Verify the exact commit
   through CI and the serialized InstaBox gate; retain audit evidence.

Authentication/authorization and production isolation must precede public deployment APIs.
Kubernetes, billing, autoscaling and AI agents remain out of scope.

## Earlier control-plane plan (superseded by current slice below)

PR #1 is merged. The current authorized sequence is01.1 domain schema;01.2 sessions/auth;
01.3 ownership/tenant roles;01.4 projects;01.5 environments/services;01.6 immutable deployment
metadata/state machine;01.7 real dashboard/browser journeys;01.8 security/acceptance hardening.
No customer containers, build engine execution or networking adapters are authorized here.
Before01.1, protected auto-merge must be configured and verified. The owner has since resolved
that prerequisite; see current slice status below. The Codex integration still cannot mutate
repository administration settings, and no permission bypass is allowed.
See engineering/state/progress.json for the durable checkpoint and exact acceptance status.

## Current authorized slice (supersedes earlier stale prerequisite status)

PR2 merged at aae350a6cf2ed10bea09f9ec4aa3075ae038d0a8. Owner-applied active main ruleset
requires `engineering-controls` and `checks` from GitHub Actions, strict updates, no bypass
actors. Native squash auto-merge is available; unknown/failed checks still block merge.

The latest explicit user request expands01.1 to a working Project/Service/Ownership API with
a minimal secure authentication boundary. It does not authorize a deployment engine or browser
dashboard implementation in this slice. Deliver owned project CRUD, nested service metadata,
safe archival, PostgreSQL integrity/migrations, independent security review, deterministic scoped
evals and verified CI. Minimal CLI-provisioned API tokens do not satisfy the later browser
registration/login/logout/session acceptance cases. Those remain unexecuted until implemented.

Do not start01.2 until01.1 passes and actually merges. Then the recommended next slice is the
browser authentication/session boundary and tenant-role design, followed by environments,
deployment metadata, dashboard/user journeys and hardening as separately accepted scope.
No customer-container execution or Phase02 work is authorized here. A failing postmerge
InstaBox run blocks advancement and must be reported without automatic destructive rollback.

## Current01.2 authorization

Slice01.1 actually merged in PR3 at2c78551bd9ecfd144a114c20c3716d07440a083f; its actual trusted
InstaBox run40167400907 passed for that merge SHA. Its checkpoint had9 applicable evalpasses
and11 broader scenarios outstanding. The current authorized01.2 adds password provisioning,
browser sessions, CSRF/login-abuse controls and a real responsive SvelteKit dashboard connected
to existing project/service APIs. No public signup, environments, deployment engine, Railpack,
customer containers, Kubernetes, billing or autoscaling is authorized. Preserve6specialists,
strict enforcedchecks and oneaggregate repair/retest. Do not start01.3 before01.2 passes and
actually merges. Recommended01.3 is tenant/membership roles and environment-scoped metadata,
subject to the next explicit scope; no persistent coding runner is active.
