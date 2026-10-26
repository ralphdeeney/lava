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

The worker has no Docker socket. The integrated executor described below adds
authenticated transport, durable replay protection and controlled-process
recovery. Database publication is fenced; cancellation of a Docker client still
does not prove that daemon-side build activity stopped. An uncertain external
outcome must never be interpreted as safely terminated work.

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

This is fixture-only build verification. The default worker remains simulated;
test probes and the protected-main build harness opt into the authenticated
executor. No customer source or persistent-VM build is permitted. Build work can run more than once after a
crash; fencing protects metadata, not external execution.

## Integrated executor (Stage A)

`python -m lava.executor` is a separate, non-root Unix-socket daemon. The API
never receives its socket or key. The worker connects with a read-only runtime
mount. Linux peer credentials, an owner-private directory, a 0600 socket and a
32-byte owner-only key are all required. Protocol version 1 uses the signing-key
slot `local-v1`; HMAC authenticates the complete operation, job/deployment and
execution identities, source/configuration revision, nonce, lease token/owner,
claim generation and deadline. Authentication alone grants no execution rights:
the executor locks the job row and independently checks PostgreSQL ownership.

Provision the key once with `python -m lava.executor --socket /private/sock
--key-file /private/key --provision-key`. Provisioning refuses overwrite and
symlinks. Rotate by stopping worker/executor, provisioning a fresh owner-only
file, switching both services to that file, and restarting them. Old signatures
then fail closed; no overlapping old-key acceptance is provided. Never print a
key or pass it in argv/environment. The shared UID is a dedicated runtime UID
inside separate containers; same-user host processes are trusted. This is not
an isolation boundary for arbitrary hostile same-UID host code.

Migration 0009 stores one execution identity per job claim and globally unique
hashed request nonces. Reusing an identity with a fresh nonce resolves the same
execution; replaying the same envelope is rejected. Expired nonces can be
removed after 24 hours because expired requests are independently rejected.
A restricted `lava_executor` role can read job/source metadata, insert execution
and nonce rows, update execution outcomes and request cancellation. It cannot
read accounts, alter leases, own schema objects, or run migrations. Daemon startup
rejects powerful or inherited roles. Worker and migration roles remain separate.

The owned wrapper process records a durable execution nonce and completion
receipt in a private spool. It kills its own child process group with bounded
TERM/KILL handling before publishing a receipt. Cancellation uses private marker
files, not recovered PID signals. On executor restart, receipts are reconciled;
missing evidence remains UNKNOWN and blocks queue reclamation. A bounded scan
runs every 500 ms, propagates cancellation/lease loss, and stops owned work on DB
uncertainty. A singleton filesystem lock and session advisory lock prevent two
executors from adopting the same spool/database. A lost advisory connection
causes fail-closed exit. A current worker can adopt a proven completed receipt
without rerunning external work. Artifact, job and deployment updates commit in
one lease-fenced transaction; real builds stop at BUILT and never become ACTIVE.

`compose.executor-probes.yaml` is an explicit test-only overlay. Supply a separate
`POSTGRES_EXECUTOR_PASSWORD` and use it with `compose.yaml`; it replaces the
simulated worker with the socket client. It provisions a private shared key,
uses a read-only worker mount, and exposes no executor port or Docker socket.
The verifier's `--executor-probes` option creates an owned disposable stack and
checks an actual worker/daemon/process/database round trip. Its 4 GiB preflight
is unchanged. Fixed sleep probes are simulations and create no OCI artifacts.

The fixture-build daemon mode is restricted to protected-main disposable GitHub
push runs. It verifies source/fixture/toolchain identity, runs approved argument
arrays, exports OCI archives and verifies manifest/blob hashes. The trusted
harness runs the worker in a non-root read-only container with no Docker socket;
only the separate host executor has Docker authority. Checkout credentials are
not persisted. BuildKit client cancellation cannot by itself prove that all
Docker-daemon work stopped: such outcomes remain UNKNOWN and are not retried.
The entire disposable runner is the final external cleanup boundary. This is a
remaining real-build cancellation acceptance gate, not proof of termination.
Current PR-head image builds are still unavailable under this policy, so PR #9
must remain draft until an approved trusted verification path supplies that
evidence. Neither an earlier commit's images nor controlled probes satisfy it.
