# Phase 00 verification

Verified in Codex Cloud on 2026-10-24; this is not an InstaBox result.

- `scripts/bootstrap.sh` completed twice after fixes, including frozen pnpm/uv installs.
- Ruff check and format check passed (14 Python files).
- Final combined backend run: 8 passed, 0 skipped, 1 upstream warning (3.60 seconds).
  This comprises 7 unit tests and 1 PostgreSQL integration test against a
  disposable PostgreSQL 17.9 container: upgrade, write, downgrade, unready schema,
  re-upgrade, and Alembic schema-drift check. No zero-test run is counted as validation.
- Svelte check: 0 errors, 0 warnings. Production build passed locally and in the pinned
  Node 22.23.0 image; container builds also run Svelte check.
- Compose cloud override builds with verified TLS via a CA build secret. Functional smoke
  checks passed for frontend HTML, `/health` JSON and database-backed `/ready` JSON.
- PostgreSQL outage behavior: `/health` 200 and `/ready` 503; DB restarted afterward.
- Compose configuration assertions: no DB host port, loopback-only HTTP ports, no API socket
  mount. API UID 10001 and frontend UID 1000 were verified in running containers.
- Shell syntax and Git whitespace checks passed.

Host: Python 3.13.5, Node 24.19.0, uv 0.12.23, pnpm 10.32.1, Docker 28.4.0,
Compose 2.40.3. The containerized Node build uses the pinned Node 22 version.

One upstream Starlette/httpx test-client deprecation warning remains. It does not skip tests.
CI is configured but has not run on GitHub in this task. The feature branch is committed
locally, not pushed. No connection to `agent-development` was attempted; its specific Docker,
Compose and Node patch versions remain unverified. Run the documented bootstrap and smoke
gate there after transferring the branch through GitHub. Railpack, BuildKit execution worker,
Traefik, deployments, auth and production hardening are intentionally future work.

The exact changed-file list is available with `git show --stat HEAD` and
`git diff-tree --no-commit-id --name-only -r HEAD` after the Phase 00 commit.
