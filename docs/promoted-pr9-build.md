# Protected promotion for PR #9

`promoted-fixture-build-9.yml` is a one-time, manually dispatched workflow on
protected `main`. Its YAML pins one reviewed PR #9 source commit. Changing that
commit or the audited Python, Node, Go, cancellation, and failure fixture hashes requires a protected
merge. The workflow has a read-only repository token, persists no checkout
credentials, references no repository or environment secrets, and runs on a
disposable GitHub-hosted runner. It checks the exact commit, clean checkout,
fixture hashes and symlinks, and 4 GiB of free space on both source and Docker
storage before candidate code executes.

The promoted candidate contains executable Python, dependency lockfiles and a
Dockerfile. Docker access grants effective host authority on that disposable
runner. The protected promotion is therefore an explicit trust decision about
the *entire pinned candidate tree*, not merely the fixture sources. Security
review of that exact SHA is mandatory before merging this workflow. A new
candidate SHA requires another protected review and workflow change; passing
tests on an earlier SHA never verifies a later PR head. Do not add PR-controlled
inputs, `pull_request_target`, a write token, or InstaBox credentials here.

The build harness provisions only disposable PostgreSQL roles, runs the worker
without a Docker socket, and records immutable OCI digests in its disposable
database. Its dedicated BuildKit v0.34.0 builder is version- and digest-pinned;
the harness tests success, cancellation, failure, and timeout and checks the
builder stopped on unsuccessful work. The workflow publishes bounded fixture
evidence and removes only its named database. GitHub destroys the runner after
the job. These tests are requirements; no result is inferred from this workflow
file until it actually runs on the promoted commit.
