# Development

## Fresh machine

Clone `https://github.com/ralphdeeney/lava.git` and check out the desired feature branch.
Prerequisites: Linux, Git, Docker Engine + Compose v2-compatible CLI, Python 3.13.5,
uv 0.12.23, Node 22.23.0 or compatible Node 22, and npm. The bootstrap installs pnpm 10.32.1
locally into the selected cache directory. Python/JS direct dependencies and transitive locks
are committed. Docker base images use explicit version tags and immutable manifest digests.

On InstaBox `agent-development`, Docker 29.8.2, Compose 5.6.0, Python 3.13.5 and Node 22.23.3
are the expected operator-provided tools. No direct Codex-to-VM connectivity is assumed.
Transfer work through GitHub: push the branch from an authorized workstation, then clone/fetch
and check it out on the VM. Local commits are not automatically pushed.

Before building on the approximately 8 GiB VM, mount a separate data disk. Inspect Docker `data-root` first. Changing it requires explicit operator authorization;
only then preserve existing daemon settings and migrate any existing data safely with Docker
stopped. The verification script never changes storage settings. Use `docker info --format '{{.DockerRootDir}}'` to
verify. Merely setting BuildKit cache variables does not relocate Docker layers or volumes.
Do not use a directory on the root filesystem as a substitute for a mounted data disk.
Set the cache path to that disk and run builds sequentially:

```sh
export LAVA_CACHE_DIR=/data/lava-cache  # replace with your actual mounted disk path
export UV_CACHE_DIR="$LAVA_CACHE_DIR/uv"
export npm_config_cache="$LAVA_CACHE_DIR/npm"
export PATH="$LAVA_CACHE_DIR/tools/node_modules/.bin:$PATH"
./scripts/bootstrap.sh
COMPOSE_PARALLEL_LIMIT=1 ./scripts/smoke.sh
```

Bootstrap preserves existing .env, creates a random password only when missing, installs frozen
dependencies and automatically runs unit/lint/type/build checks. Inspect any existing .env for
valid values. Never source an untrusted .env as a shell script. Re-running bootstrap is safe.
Smoke starts Compose, waits for health, checks API JSON and dashboard HTML. It leaves services
running for development. `docker compose down` preserves PostgreSQL; `down -v` deletes its data.
Do not prune shared Docker caches without checking what other projects need.

Compose runs built artifacts. After edits rerun `docker compose up --build --wait`.
For frontend live reload, stop Compose web then run `pnpm --filter @lava/web dev --host 127.0.0.1`.
For API live reload, use the container workflow or provide LAVA_DATABASE_URL for an independently
reachable development database and run `uv run --project apps/api uvicorn lava.main:app --reload`.
The default Compose database deliberately has no published port.

## Tests and migrations

```sh
./scripts/check.sh
# For a disposable reachable PostgreSQL database only (this test downgrades/deletes tables):
cd apps/api
export LAVA_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DISPOSABLE_DB'
LAVA_INTEGRATION=1 LAVA_TEST_DATABASE_RESET=1 uv run --locked pytest tests -m integration
uv run --locked alembic upgrade head
uv run --locked alembic check
```

Unit tests cover liveness, readiness outcomes, configuration redaction/validation, DB failure,
and structured request logging. The release gate uses pinned httpx2 (the test client
recommended by Starlette) and treats deprecation warnings as errors. It also tests verifier
redaction, unsafe configuration rejection and project-scoped failure cleanup.
Integration tests verify real PostgreSQL writes, upgrade/downgrade/re-upgrade and schema drift.
CI runs unit/lint/type/build, PostgreSQL integration and Compose smoke on GitHub-hosted Linux.
A workflow file is not evidence of a GitHub Actions run; inspect its result after pushing.

When running inside Codex Cloud, package caches should use a writable workspace directory.
Proxy build steps accept optional BuildKit secret `proxy_ca`; keep verification enabled.
Supply the session's combined trust bundle through a local Compose override, not committed
credentials. A normal VM needs no override. No external services/secrets are required beyond
GitHub/package registries and the local generated database password.

For this managed cloud runtime the reproducible override is committed:

```sh
export BUILDX_CONFIG="$LAVA_CACHE_DIR/buildx"
mkdir -p "$BUILDX_CONFIG"
COMPOSE_FILE=compose.yaml:compose.cloud.yaml COMPOSE_PARALLEL_LIMIT=1 ./scripts/smoke.sh
```

`compose.cloud.yaml` mounts the host combined CA bundle as a build secret. It contains no
credentials and does not copy trust material into application image layers. Normal VM builds
use only compose.yaml. Build artifacts/processes are regenerated; the data volume persists.


## InstaBox release gate

The implementation and follow-up fixes must be fetched from GitHub. Never assume a VM checkout
contains changes made only in Codex. On `agent-development`, after fetching the feature branch:

```sh
git fetch origin feat/phase-00-foundation
git switch feat/phase-00-foundation
git pull --ff-only
# Compare this SHA with the published release-verification SHA before continuing.
git rev-parse HEAD
# If uv is missing, provision it on the already-mounted, writable /data disk:
python3 -m venv /data/lava-tools
/data/lava-tools/bin/python -m pip install uv==0.12.23
export PATH="/data/lava-tools/bin:$PATH"
uv --version  # must report 0.12.23
./scripts/verify-instabox.sh --preflight-only
export LAVA_CACHE_DIR=/data/lava-cache
export UV_CACHE_DIR="$LAVA_CACHE_DIR/uv"
export npm_config_cache="$LAVA_CACHE_DIR/npm"
export PATH="$LAVA_CACHE_DIR/tools/node_modules/.bin:$PATH"
./scripts/bootstrap.sh
./scripts/verify-instabox.sh
```

The verifier checks Python 3.13, Node >=22, uv 0.12.23, Compose >=2.24.4, Docker connectivity,
permissions and disk space. `/data` must already be a writable, separately mounted filesystem;
Docker data-root must be on that filesystem. If it is not, stop and obtain operator authorization
before any storage migration. No script edits daemon configuration or moves Docker storage.

It uses a random `lava-verify-*` project, private temporary credentials, an isolated database
volume, and dynamically assigned loopback HTTP ports. Existing development services, ports,
.env and data remain untouched. HTTP/DB checks, repeated migration upgrade and schema checks
run before project-scoped teardown. It removes only its own containers, network, volume and
locally tagged build images; it never prunes global resources. Bounded diagnostics (at most
64 KiB) remain mode 0600 under `/data/lava-verification/run-*`; passwords and database URLs
are redacted and the temporary credential file is removed. SIGINT/SIGTERM trigger teardown;
SIGKILL or host failure cannot be trapped, so inspect leftover `lava-verify-*` projects manually
rather than pruning all resources.

For ephemeral GitHub runners/Codex Cloud only, `--data-dir <existing-writable-directory>
--allow-root-storage` explicitly permits the runner's existing daemon storage without moving
it. Add `--cloud` for the managed CA build secret. The cloud host may need the Python 3.13
virtualenv's bin directory on PATH. Do not use the root-storage override to ignore the VM's
20 GB data-disk requirement. GitHub Actions runs this same disposable gate automatically.

The destructive pytest migration suite additionally requires `LAVA_TEST_DATABASE_RESET=1`
and a database name ending in `_test`; these checks precede all migration commands. This is
an explicit acknowledgement, not proof that an arbitrary database is safe. Use only a new,
disposable database. Regular migration `upgrade head` remains non-destructive and repeatable.

## GitHub Actions → InstaBox (no interactive SSH)

`InstaBox Phase 00` runs on trusted pushes to main and the Phase 00 feature branch, or by
workflow dispatch. It uses repository secrets `INSTABOX_API_KEY` and `INSTABOX_MACHINE_ID`.
The API key needs `machines:write` (which includes read access); no delete, image, billing or admin
scope is used. Untrusted pull-request events do not receive these secrets. The key is sent
only in an HTTPS header to the fixed `https://api.instabox.sh` origin; redirects are refused.
Neither the API key nor GitHub credentials are forwarded to the VM.

The runner checks machine name, explicit free-tier status, readiness, operation state, runtime
cap and cooldown before execution. It never creates machines, changes plans, grows disks,
modifies Docker storage, publishes VM ports or bypasses lifecycle restrictions. A normally
running machine needs no lifecycle change. Idle suspension uses the documented wake route;
manually paused machines need the workflow's explicit `allow_resume` input. Stopped machines
and billed/unknown-price machines fail closed. Resume uses a stable idempotency key and polls
the returned operation. 401/402/403 and cooldown/account restrictions are not retried away.

The Actions checkout is fetched with full Git history and without retained GitHub credentials.
A Git bundle is transferred through API exec stdin, cloned under the newly allocated
`/data/lava-ci/runs/<run-id>-<attempt>/checkout`, and checked out detached at the full intended
SHA. Existing operator checkouts are untouched. The API stdin limit is enforced; oversized
bundles fail rather than using an unverified transfer path.

A bounded VM worker runs bootstrap, the complete PostgreSQL-backed pytest suite and the
real disposable Compose verifier. GitHub concurrency and a VM flock serialize infrastructure
runs. Package caches and Docker data stay on /data; the existing daemon configuration is only
inspected. Diagnostics are redacted, private and at most 64 KiB; exact commit, step completion
and exit code are published as a seven-day Actions artifact. The source bundle, disposable
checkout (including .env), test DB and run-owned Compose resources are cleaned up. Operator
services/volumes and shared package caches are preserved.

The API's exec endpoint is not idempotent. Unknown launch responses are reconciled by reading
the owned run's status; they are never blindly replayed. Read-only polling and explicitly
retryable rejections have bounded retries, with Retry-After honored within the retry budget.
The API request timeout is 60 seconds per command, VM job deadline 20 minutes and Actions job
deadline 30 minutes. A background worker is used so legitimate builds do not exceed the API's
600-second execution cap. SIGTERM/timeouts trigger scoped cleanup; host failure/SIGKILL may
require inspecting the named run and its lock before recovery, never global pruning.

An API acceptance response or a mocked protocol test is not VM integration evidence. Only a
terminal, zero-exit result for the exact SHA, with completed required steps and successful
cleanup, satisfies the automated VM gate. Inspect both `Phase 00` and `InstaBox Phase 00`
checks on the PR before merging. Phase 01 remains blocked until that merge is authorized.


The implementation was checked against the live official `/v1/openapi.json` contract (API
version 1.0.0) through Actions. Cloud egress does not need direct VM/SSH access. Required API
fields, exec stdin/timeout limits and non-idempotent replay semantics come from that contract.
The first real automated gate succeeded at commit
`8f00d9af1abd3c28b71d2dcc7f2b5736b039fa1d`:
https://github.com/ralphdeeney/lava/actions/runs/40111964466 . Subsequent changes must pass
both workflows for their own SHA; never substitute this historical run for current evidence.

## Phase01 pipeline preparation status

Phase00 is merged, but Phase01 product work is not started. Native implementation, QA, security,
architecture/evaluation and user-simulation specialists contributed independent scoped reviews.
No persistent coding runner exists. See engineering/README.md for the executable one-repair
interfaces, real GitHub-policy observation and blocked checkpoint. The Phase01 evaluation
catalog is a specification with20 not-run cases, not evidence of application functionality.
Protected merge policy and a trusted infrastructure-controller boundary must be resolved first.

## Slice01.1: owned project/service APIs

Use the existing Compose setup (`./scripts/bootstrap.sh`, `docker compose up --build --wait`).
Migration0002 preserves existing projects, assigning them to a disabled quarantine identity.
No existing project becomes accessible to a newly provisioned user automatically. The new
API remains bound to loopback and has no Docker socket or deployment execution.

Provision a disposable local API identity in a private terminal:

```sh
docker compose exec api python -m lava.auth.provision create alice --ttl-hours 24
```

Store the returned token in a secure API client's credential store and use the HTTP
`Authorization: Bearer` scheme. Do not paste it in URLs, source, chat, shared logs or shell
history. Provision another identity to exercise isolation. The CLI needs trusted database
access; it is not a public registration endpoint. Token expiry and revocation take effect
on subsequent requests. See [ADR0001](docs/adr/0001-control-plane-authentication.md).

API resources (authenticated; identifiers are UUIDs):

| Method | Path | Behavior |
| --- | --- | --- |
| POST / GET | `/projects` | Create / list own projects (bounded pagination) |
| GET / PATCH / DELETE | `/projects/{project_id}` | Retrieve / update / archive |
| POST / GET | `/projects/{project_id}/services` | Create / list services under owned project |
| GET / PATCH / DELETE | `/projects/{project_id}/services/{service_id}` | Retrieve / update / archive |

Project input includes `name` and optional `description`. Service input includes `name`,
`service_type` (`web`, `api`, `worker`, `database`), `resources` (`cpu`, `memory_mb`), and optional
`desired_state` (`stopped`, `running`). Desired state is metadata only. No container is started.
Archive is idempotent; archived records remain readable and names reserved. Updates and child
creation under archived parents are rejected. No DELETE endpoint removes physical rows,
persistent volumes or deployed resources. Cross-owner and wrong-project service lookups return
404. Missing/invalid credentials return401; invalid input422; duplicates/lifecycle conflicts409.
Errors do not echo input bodies, bearer tokens or database exception details.

To revoke, use the credential identifier returned by provisioning (not the token):

```sh
docker compose exec api python -m lava.auth.provision revoke CREDENTIAL_UUID
```

The migration history is preserved. Upgrade is repeatable. Downgrading an empty/quarantined
legacy schema is supported; rollback refuses data loss once new owned projects, credentials or
services exist. Back up and use a reviewed forward migration for operational recovery. Do not
remove persistent records just to force a downgrade. Production DB-role separation, HTTPS and
browser/account authentication are still prerequisites for public deployment.

The independent real-PostgreSQL API suite requires a newly allocated disposable `*_test` DB
and both existing safety flags. It covers ownership, CRUD, invalid/duplicate configuration,
archive behavior, token expiry/revocation, constraints and rollback. CI publishes actual JUnit
results and a scoped evaluation report; unimplemented Phase01 scenarios remain `not_run`.
The trusted-main InstaBox workflow verifies the squash-merge commit after independent review;
no unreviewed PR is dispatched with infrastructure credentials.

## Slice01.2: browser authentication and dashboard

After bootstrap and Compose startup, privately provision/reset a browser account:

```sh
docker compose exec api python -m lava.auth.accounts provision alice
```

This prompts without echo, confirms the password and revokes all prior browser sessions for
that user. There are no default passwords or public registration. `--password-stdin` is only
for a secure administrative stdin channel; never put passwords in command arguments/history,
logs or source. Existing bearer provision/revoke commands remain independent.

Open http://localhost:3000/login, then use Projects to create/manage real owned projects and
nested service metadata. Account/session controls show the current session expiry and revoke
current/all sessions. Logout invalidates the server record. No displayed state represents
running customer containers. Desktop/mobile forms have labels, visible focus, navigation,
empty/loading/error states and no fictional metrics.

Set LAVA_BROWSER_ORIGIN to the exact browser origin; web ORIGIN must match. Compose forwards
that value to both services and sets private LAVA_API_ORIGIN=http://api:8000. For HTTPS use
LAVA_COOKIE_SECURE=true; production configuration requires both HTTPS and Secure cookies.
When running separate production processes, set the private API URL on the SvelteKit server,
not a PUBLIC_ browser variable. Do not trust arbitrary forwarded/client IP headers.

For disposable real-PostgreSQL testing, retain LAVA_INTEGRATION=1 and
LAVA_TEST_DATABASE_RESET=1 and a freshly allocated *_test database. After frozen install,
frontend build and migrations:

```sh
pnpm exec playwright install --with-deps chromium
uv run --project apps/api --locked python scripts/verify_browser.py
```

Managed Cloud can use existing Chromium via LAVA_E2E_CHROMIUM=/usr/bin/chromium when the
Playwright CDN is not allowed. This is actual Chromium automation, not a mocked browser.
The verifier starts loopback API/web processes, provisions random users, saves a private0600
fixture and runs the16 desktop/mobile journeys without mocked endpoints. Test-only fixture
helpers adjust only owned test sessions/buckets, never production data or public endpoints.
Raw logs remain under ignored harness-private paths; public sanitized outcomes are under
`test-results/e2e/public`. No traces/videos or credentials are published. The private account
file is removed and owned users/projects/services/sessions cleaned even after ordinaryfailure.
Do not upload the entire test-results directory. CI publishes only explicit sanitized paths.

## Slice 01.3: collaboration and environments

Start with `./scripts/bootstrap.sh` and the existing loopback-bound Compose stack. Apply
`alembic upgrade head` before starting the updated API; readiness requires migration0004.
The migration backfills each existing project's Owner membership and leaves previous services
unassigned to an environment. Do not reset a persistent database or delete existing rows to
upgrade. `alembic downgrade` refuses if new membership, invitation, environment or changed
service configuration data would be lost.

Provision each collaborator with the existing private account command, then use the project's
Members page to add an existing user or create an invitation. The invitee sees their own
pending invitations after login and accepts or declines while authenticated. No email or
public registration is configured. Owner/Admin can manage non-owner memberships. Developer
can edit service and environment metadata; Viewer can only read. See ADR0003 for the full
server-enforced matrix and invitation trust model.

The Environments page creates, lists and archives development, staging, production or custom
environment metadata. A service may point to an environment in its own project and may record
validated build preference, start command, branch, resource limits and desired replicas. These
settings do not execute deployments. Do not put secrets in the configuration fields; this slice
provides no environment-variable secret store.

The disposable `*_test` PostgreSQL suite verifies migration0004, membership/role integrity,
invitation lifecycle, tenant isolation and service/environment foreign keys. The browser
verifier exercises the real API/web processes and publishes only sanitized outcome metadata.
Candidate code runs on GitHub-hosted CI without InstaBox secrets; the serialized trusted-main
workflow verifies the merge SHA on the VM after protected merge.
