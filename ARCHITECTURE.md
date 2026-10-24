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
The initial projects table establishes migration discipline; no project/deployment API exists yet.

Phase 01 will add application services and domain modules here without reorganizing the tree.
Railpack + BuildKit adapters will implement BuildEngine. A separate worker will invoke those
adapters and Docker ContainerRuntime. The API will enqueue deployment IDs through
DeploymentScheduler; it will never receive Docker socket access. Networking will be implemented
by a Traefik adapter. Protocols define the boundary only; retry/idempotency, cancellation,
resource limits and durable deployment state transitions must be specified before execution.
No Railpack, BuildKit daemon, Traefik or worker service is installed in Phase 00.

Compose publishes frontend/API on host loopback only. PostgreSQL has no host port.
A browser can load the dashboard independently of API readiness; the page intentionally makes
no claim about live deployment state. No public deployment or authentication surface exists.
