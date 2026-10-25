# ADR 0006: Durable deployment jobs and worker leases

Migration 0007 adds one durable job per deployment. Job claims use PostgreSQL row locks with
`SKIP LOCKED`, a lease owner, hashed opaque token, and monotonic lease generation. Every
heartbeat, completion, retry, and cancellation write is fenced by job identity, owner, token,
and an unexpired lease. Expired jobs are reclaimable without creating another deployment.

The worker runs as a separate non-root Compose process with no host socket and no public port.
Its executor is deterministic and simulated; it never invokes user commands or build/runtime
tools. Job processing is at-least-once. Database idempotency and fencing prevent duplicate
state changes, but they do not claim exactly-once external execution. Cancellation and retry
state are durable, and terminal deployment transitions continue through the existing protected
deployment service.
