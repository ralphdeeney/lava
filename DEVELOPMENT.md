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

Before building on the approximately 8 GiB VM, mount a separate data disk. Have the operator
configure Docker `data-root` there, preserving existing daemon settings and migrating any
existing data safely with Docker stopped. Use `docker info --format '{{.DockerRootDir}}'` to
verify. Merely setting BuildKit cache variables does not relocate Docker layers or volumes.
Do not use a directory on the root filesystem as a substitute for a mounted data disk.
Set the cache path to that disk and run builds sequentially:

```sh
export LAVA_CACHE_DIR=/mnt/lava-data/cache  # replace with your actual mounted disk path
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
LAVA_INTEGRATION=1 uv run --locked pytest tests -m integration
uv run --locked alembic upgrade head
uv run --locked alembic check
```

Unit tests cover liveness, readiness outcomes, configuration redaction/validation, DB failure,
and structured request logging. The current Starlette test client emits an upstream httpx
deprecation warning; tests still execute and pass.
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
