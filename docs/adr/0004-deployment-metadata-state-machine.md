# ADR 0004: Deployment metadata and lifecycle state

LAVA stores deployment identity and lifecycle metadata in PostgreSQL while execution remains
outside the API process. A deployment snapshots its project-scoped service and environment,
source commit, branch, and configuration revision. The `(project_id, service_id,
idempotency_key)` constraint makes creation repeatable without allowing a key to refer to a
different immutable snapshot.

Lifecycle transitions are performed by the application service under a row lock and append an
ordered event. Public users can create and read metadata according to existing project roles;
they cannot transition lifecycle state. Future workers will use a separate privileged internal
interface. Terminal states are immutable. Failure messages are bounded and sanitized.

Migration 0005 is additive and retains all existing control-plane data.
