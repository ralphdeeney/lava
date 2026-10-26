# ADR 0007: Trusted fixture builds on disposable CI runners

Railpack 0.43.0 prepares Python, Node, and Go fixtures from the audited
`build-fixtures/` tree. Its release archive is SHA-256 verified. Docker BuildKit
uses the pinned Railpack frontend image digest and a disposable GitHub runner
with the containerd image store, which Railpack requires for `mergeop`.
The Docker-capable job runs only from protected `main`; pull requests run the
PostgreSQL worker prerequisite job without build authority. Premerge fixture
builds require a separate trusted workflow and audited fixture hash baseline.
The verifier rejects a checkout whose commit differs from `GITHUB_SHA`, any
non-main ref, fixture-tree changes from its audited hashes, symlinks in fixture
trees, and a BuildKit version other than v0.34.0. Changing those approvals is
a protected-code review decision, not a runtime input.

## Threat model and premerge boundary

A pull request author controls the candidate tree, including GitHub workflow
files, Python verification scripts, Dockerfiles, fixture content, and package
hooks. Docker daemon access on a runner effectively grants that job host-level
control. Therefore a normal `pull_request` job cannot safely check out and
execute candidate scripts or build contexts with Docker authority, even on an
ephemeral runner. `pull_request_target` with candidate checkout has the same
problem and is prohibited. The runner has no repository write token or
infrastructure secret; this limits impact but does not make unreviewed code
trusted. The current protected-main-only job deliberately leaves current-head
premerge real builds unverified.

A safe premerge design needs a harness fetched exclusively from a protected
revision, a separate disposable Docker runner, immutable allowlisted fixture
tree hashes and tool digests controlled by that revision, and candidate SHA
treated as untrusted data. Such a harness can verify that an approved fixture
builds, but cannot execute modified candidate builder code and claim it has
verified that code. Testing candidate builder changes requires a stronger
isolation mechanism or a protected promotion step before Docker-capable
execution. This boundary has not yet been implemented; PR #9 must remain
draft. A green `checks` result does not attest to real candidate builds.

The simulated deployment worker has no Docker socket and no authenticated
executor transport. Build results are currently recorded only by the trusted
fixture verifier in disposable CI PostgreSQL. The job lease fences database
publication, but does not cancel a BuildKit process or prove that abandoned
external work stopped. A future executor needs scoped request authentication,
an immutable source/configuration allowlist, durable request nonces, lease-
generation fencing at submission, process-group or BuildKit cancellation,
timeout, and an `unknown` reconciliation state when executor contact is lost.
It must never interpret an uncertain outcome as a safely terminated build.

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
