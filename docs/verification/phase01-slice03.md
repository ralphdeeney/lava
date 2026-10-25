# Slice 01.3 verification record

Base/main: `658a0071852d62e25bd1ac51bae4a2e2ff06e872`. Branch:
`feat/phase01-slice03-tenancy-environments`. Draft PR: #5. One aggregate repair is in progress;
the slice is not accepted until its single complete retest and exact-head GitHub checks pass.

Initial clean implementation commit: `1602b376dea6b0a3906015dc2c284f8634baa50e`.
The initial local gate passed 37 backend unit tests, 142 engineering tests, Ruff/format,
Svelte checks with zero errors/warnings, browser TypeScript and production build. Real
PostgreSQL integration was 107 passed/5 failed. All 26 Playwright journeys executed against
real FastAPI, SvelteKit and PostgreSQL: 24 passed, 2 failed. The two failures were one
ambiguous `Members` heading locator in desktop/mobile; the page rendered. Evaluation reports
correctly rejected failed database and browser evidence. Disposable Compose cleaned owned
resources but its build failed TLS validation because the cloud override used a CA bundle
without the managed proxy issuer. Candidate InstaBox execution was not attempted.

The five PostgreSQL failures were legacy migration test regressions: backfilled Owner
memberships needed scoped fixture cleanup, and two revision assertions expected an
intermediate revision even though Alembic rolled the failed downgrade command back to 0004.
The first failed cleanup left an owned test row that caused later cases to fail. The aggregate
repair updates only those fixture/transaction assertions, the exact browser selector, and the
cloud-only CA mount. It does not relax downgrade guards, browser permission assertions or TLS.
See `engineering/state/slice01.3.json` for machine-readable status and the Actions evidence
linked from PR #5. The full retest result will be published after it executes.
