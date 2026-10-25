# LAVA architecture

LAVA begins as a modular monolith with a separately built SvelteKit dashboard.

- `apps/web`: TypeScript, SvelteKit, Tailwind, Node adapter. No credentials in browser code.
- `apps/api/src/lava/core`: typed configuration and structured logging.
- `apps/api/src/lava/db`: SQLAlchemy models; `apps/api/migrations`: Alembic schema history.
- `apps/api/src/lava/ports`: asynchronous build, runtime, scheduler and networking protocols.
- `scripts`: repeatable developer and integration checks; `.github/workflows`: CI.

The API owns control-plane HTTP endpoints and persistence. Health is independent of the database;
readiness requires a successful query and the expected migration revision. A one-shot migration
service runs before the API. There is no automatic schema creation on API startup.
The initial projects table established migration discipline; migration0002 now adds the owned
project/service control-plane API. No deployment execution API exists.

Phase 01 will add application services and domain modules here without reorganizing the tree.
Railpack + BuildKit adapters will implement BuildEngine. A separate worker will invoke those
adapters and Docker ContainerRuntime. The API will enqueue deployment IDs through
DeploymentScheduler; it will never receive Docker socket access. Networking will be implemented
by a Traefik adapter. Protocols define the boundary only; retry/idempotency, cancellation,
resource limits and durable deployment state transitions must be specified before execution.
No Railpack, BuildKit daemon, Traefik or worker service is installed in Phase 00.

Compose publishes frontend/API on host loopback only. PostgreSQL has no host port.
A browser can load the dashboard independently of API readiness; the page intentionally makes
no claim about live deployment state. No deployment execution exists; browser sessions are described below for Slice01.2.

## Slice01.1 control-plane boundary

Projects and services now live in the same modular monolith. Domain enums describe lifecycle
and service categories; application services enforce ownership and legal archive behavior;
persistence adapters provide request-scoped SQLAlchemy sessions; API schemas/routes provide
validated HTTP contracts. UUID ownership foreign keys and scope-specific unique constraints
are enforced in PostgreSQL. The existing migration0001 remains intact;0002 extends its schema
and quarantines legacy records under a disabled identity. Health stays unauthenticated;
readiness verifies the new schema revision.

Authentication is an expiring/revocable opaque bearer credential resolved through its SHA256
digest to an active persistent user, provisioned outside public HTTP. This is a minimal API
boundary, not the future browser account/session product. See ADR0001 for the trust model.
No API service imports/invokes Docker, runtime, build or routing adapters. Service desired-state
changes describe metadata only; DELETE archives metadata and cannot destroy infrastructure.

## Slice01.2 browser boundary

FastAPI now owns Argon2id password accounts and hashed opaque browser sessions (migration0003).
SvelteKit uses a narrow same-origin BFF and server-side protected layouts; browsers never
receive API bearer tokens. Cookie sessions and API tokens resolve to the same existing user
ownership checks. Origin+session-boundCSRF protects browser mutations; invalid bearer headers
cannot fall back to cookies. See ADR0002 for provisioning, expiry/revocation and trust limits.
