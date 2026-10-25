# Real browser acceptance

`pnpm test:e2e` runs eight functional journeys on desktop and mobile against the actual
SvelteKit application, FastAPI, and a run-owned PostgreSQL database. No network interception,
API mock, fictional account, or production credential is used. Public registration remains
outside the current browser-auth slice; fixture accounts are administratively provisioned.

The coordinating harness supplies `LAVA_E2E_BASE_URL`, a mode-0600
`LAVA_E2E_ACCOUNTS_FILE` containing two users with id/username/password,
`LAVA_E2E_EXPIRE_HELPER` and `LAVA_E2E_PYTHON`. A helper receives JSON only through stdin.
It must verify disposable database ownership and the account allowlist before expiring one
session or resetting those fixture accounts' login-attempt buckets between independent
journeys. This fixture isolation never modifies production rate limits; separate API security
tests exercise actual abuse throttling. The entire database is disposable and cleaned by its
owning harness; tests must not delete operator accounts/resources.

Use `LAVA_E2E_CHROMIUM` only to select an explicitly installed local Chromium executable.
CI should install Playwright's pinned Chromium through the normal verified download path.
The local test environment records the actual browser version; a system browser must not be
reported as the pinned bundled Chromium. `LAVA_E2E_REPORT_DIR` defaults to
`test-results/e2e/public`.

The custom reporter publishes only fixed test names, statuses, viewport, exact Git SHA and
counts in JSON/JUnit. It deliberately discards raw errors, expected/actual assertion values,
source excerpts, console/network captures and stack traces. Trace, video and automatic
screenshots are disabled because they can retain submitted passwords and cookies. On failure,
a screenshot is taken only on project screens after checking that known passwords/cookie values
are absent and masking editable/secret fields. Login screenshots are withheld. Other Playwright
outputs live under `test-results/e2e/private` and must never be uploaded as artifacts.

A report with unclean source, unknown SHA, a global runner error, missing test entries, skipped
journeys, mocks or failing assertions cannot establish the acceptance gate. Running `--list`
or merely generating report files is not executed browser evidence. Tests are run once in the
coordinator's initial aggregate, then only once after its permitted aggregate repair.
