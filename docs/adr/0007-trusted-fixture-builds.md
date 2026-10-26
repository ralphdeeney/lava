# ADR 0007: Trusted fixture builds on disposable CI runners

Railpack 0.43.0 prepares Python, Node, and Go fixtures from the audited
`build-fixtures/` tree. Its release archive is SHA-256 verified. Docker BuildKit
uses the pinned Railpack frontend image digest and a disposable GitHub runner
with the containerd image store, which Railpack requires for `mergeop`.
The Docker-capable job runs only from protected `main`; pull requests run the
PostgreSQL worker prerequisite job without build authority. Premerge fixture
builds require a separate trusted workflow and audited fixture hash baseline.

The build job receives no InstaBox credentials and does not run on the
persistent machine. It runs after PostgreSQL worker recovery tests pass. A
separate runner job owns Docker access; the Compose worker has no Docker socket
or public port. BuildKit images are named from the source commit and cleaned up
after verification. The runner enforces a 4 GiB free-disk preflight and a
bounded job timeout. Build output is bounded and redacted in failure annotations.

Migration 0008 stores immutable source/configuration snapshots and OCI image
digests in `build_artifacts`. Recording requires a live job lease, matching
owner, hashed token, and claim generation. One attempt can store one digest;
repeated identical records are idempotent. A stale builder cannot publish a
result after lease loss. The CI provenance database and images are disposable.

This is fixture-only build verification. The persistent deployment worker still
uses its simulated executor. Connecting it to a Docker-capable executor needs
an authenticated, isolated request/response boundary with cancellation and
orphan-build reconciliation. Until that boundary exists, no customer source or
persistent-VM build is permitted. Build work can run more than once after a
crash; fencing protects metadata, not external execution.
