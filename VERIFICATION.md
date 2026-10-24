# Phase 00 release verification

Verification date: 2026-10-24. No Phase 01 functionality was added.

## Publication

Implementation `e84ecf3154e8f82bf2394b2b5d3b70148f592d29` was pushed to
`feat/phase-00-foundation` and its remote SHA verified exactly. Release-verification fixes
were committed and pushed on the same branch. [PR #1](https://github.com/ralphdeeney/lava/pull/1)
is open against `main`; this task does not merge it. Use the PR head and check results for the
latest documentation-inclusive commit SHA.

The implementation's [push CI](https://github.com/ralphdeeney/lava/actions/runs/40107468408)
and [PR CI](https://github.com/ralphdeeney/lava/actions/runs/40107865710) passed.
The first verification fixes at `907f04d3a0a31836e287c64fb9e9ba002531ebd1` also passed full
[push CI](https://github.com/ralphdeeney/lava/actions/runs/40107971962) and
[PR CI](https://github.com/ralphdeeney/lava/actions/runs/40107975784), including the disposable
Compose gate. Subsequent commits rerun the full workflow; final HEAD results are linked in
the PR checks and the release report rather than treating an earlier run as HEAD evidence.

## Clean checkout and local results

A separate fresh clone was fetched from GitHub (not copied from the working tree), using
separate initially empty npm, pnpm and uv caches. Bootstrap completed and was repeated after
fast-forwarding to `b4ecd9c94799fd515a2076b584d8d4ee561b2354`.
The clean checkout remained unchanged after installation, tests and teardown.

- Frozen pnpm/uv installs: passed. Direct dependencies, transitive locks and base image
  digests are pinned. GitHub Actions themselves use versioned upstream action tags.
- Ruff check and formatting: passed for API and verifier Python files. Shell syntax and Git
  whitespace checks passed.
- Backend combined run: **17 passed, 0 skipped, 0 warnings** (15.25 seconds), including real
  PostgreSQL migration integration and operator-script safety tests.
- Separate repeat of destructive migration integration: **1 passed**, 16 deselected
  (8.81 seconds), using the same disposable database; upgrade/downgrade/re-upgrade and schema
  drift checks passed again. The test verifies that a downgraded schema is unready.
- Svelte checks: **0 errors, 0 warnings**. Production builds passed on the host and in the
  pinned Node 22.23.0 container.
- The actual `scripts/verify-instabox.sh` entry point passed in Codex Cloud, using its explicit
  ephemeral-storage override and cloud CA secret. Compose startup, frontend HTML, health and
  readiness JSON, PostgreSQL SQL query, repeated `upgrade head`, `alembic check`, non-root
  public services and project-scoped teardown all passed from the clean clone.
- Default development stack remained running and unaffected. Disposable test containers and
  volumes were removed. The verifier never changes Docker storage or prunes global resources.

Host tools: Python 3.13.5 (explicitly selected virtualenv), Node 24.19.0, uv 0.12.23,
pnpm 10.32.1, Docker 28.4.0, Compose 2.40.3. These are not the target VM's versions.

## Deprecation warning

Starlette 1.10.0 explicitly prefers `httpx2` and warns when falling back to `httpx`.
Confirmed against its installed source and upstream tagged pyproject. The maintained
[Pydantic HTTPX2](https://github.com/pydantic/httpx2) client is the supported path.
Replaced test-only `httpx==0.28.1` with `httpx2==2.16.0`, refreshed the uv lock and reran tests.
Deprecation warnings now fail pytest; no warning filters suppress the previous issue.
The backend production dependency set is unaffected by this test-client replacement.

## Security findings and fixes

- No live secrets found in the reviewed Git history: local generated PostgreSQL passwords,
  private-key headers and GitHub-token patterns were checked without printing values.
  This is a scoped audit, not a guarantee against every possible secret format.
- Bootstrap now creates .env atomically/exclusively at mode 0600, avoiding a readable creation
  window or following a dangling symlink. Existing configuration is preserved.
- Public services have no Docker socket, no privileged mode and no host networking. PostgreSQL
  publishes no host ports; HTTP defaults are loopback only. API UID 10001 and web UID 1000 were
  checked. Docker TCP configuration is not modified; the VM's daemon listener remains an
  operator-side check because the VM was not accessed.
- Added explicit reset acknowledgement and `*_test` target checks before destructive pytest
  migrations, with regression tests proving unsafe targets issue no migration command.
- Replaced raw CI Compose logs with bounded/redacted diagnostic collection. Three actual
  diagnostic files were checked: private permissions, at most 64 KiB, no retained credential
  files, no raw database URLs or local passwords. Multibyte output is bounded by bytes.
  The simulated failed-startup test verifies redaction and scoped cleanup.
- No administrative/destructive HTTP endpoints exist. This remains an unauthenticated local
  development foundation; public exposure, production role separation and privileged build
  isolation are not implemented or approved in Phase 00.

## InstaBox: operator-reported pass

On 2026-10-24 the operator reported that the real `agent-development` integration gate passed:

- Docker data-root: `/data/docker`.
- Available disk: 19,661 MiB.
- Compose startup, HTTP, PostgreSQL, migrations, non-root and cleanup checks: PASS.

This evidence was supplied by the operator; Codex did not connect to or modify the VM, and
raw VM logs were not independently inspected. The previous external-execution blocker is
resolved by that reported result. No Phase 01 work is authorized by this update.

The remaining test portability issue was isolated to the simulated startup-failure test:
it inherited the test runner filesystem's free space. That test now mocks disk capacity to
8 GiB free, allowing it to exercise startup failure, scoped cleanup and log redaction on
small runners. The actual verifier's 4 GiB minimum is unchanged.
