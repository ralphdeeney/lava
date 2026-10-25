# ADR 0005: Future execution worker contracts

Phase 01 persists deployment intent only. A future Phase 02 worker must claim a queued
deployment with a lease and worker identity, heartbeat before lease expiry, and use the
version-checked transition operation for every state change. A stale version or expired lease
must prevent the write. Retry budgets and cancellation are persisted decisions; a worker crash
leaves recoverable metadata and cannot fabricate `active`.

Builders, container runtimes, and routing adapters will be separate interfaces. Each receives
an immutable deployment snapshot and returns typed, sanitized results. Artifact provenance must
record digest and source commit. Runtime resources belong to the deployment lease and are
cleaned only by the owning worker or an authorized recovery operation. Logs are bounded and
redacted before persistence. No queue processor, Docker adapter, Railpack execution, BuildKit
execution, or network adapter is implemented in Phase 01.
