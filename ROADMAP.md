# Roadmap

## Phase 00 — release gate

Require frozen dependency installation, frontend checks/build, complete backend tests, real
PostgreSQL migration round trips, disposable Compose functional checks, and GitHub Actions
success for the exact PR head. The operator reports the manual agent-development gate passed;
remote Actions-to-InstaBox automation must independently reproduce it before the new automation
is declared verified. Retain sanitized evidence and serialize all shared-machine runs.

Do not merge automatically. Phase 01 remains blocked until Phase 00 is merged into main.

## Phase 01 — planned implementation slices (not started)

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
