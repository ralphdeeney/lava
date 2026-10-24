# Roadmap

## Phase 00 — engineering foundation

Gate: frozen dependency installs, frontend check/build, backend unit tests, PostgreSQL
upgrade/downgrade/schema checks, Compose functional requests, and CI definition.
Run the same gate on agent-development before declaring VM integration verified.

## Phase 01 — deployment vertical slice (future work)

Add project/application services, durable deployment state and job dispatch. Implement a separate
worker using the existing ports. Integrate Railpack + BuildKit, Docker runtime and Traefik only
after defining failure recovery, idempotency, artifact provenance and isolation controls.
Implement a single real deployment before expanding platform features.

Kubernetes, billing, autoscaling and AI agents remain out of scope.
