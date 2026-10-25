# Slice01.2 — BLOCKED after one repair

Branch:feat/phase01-slice02-browser-auth. Base/main2c78551bd9ecfd144a114c20c3716d07440a083f.
This is not a completed/merge-eligible slice. Do not start01.3 or dispatch this candidate with
infrastructure credentials. No persistent coding runner is active.

Implemented Argon2id administrator-provisioned passwords, server-managed expiring/revocable
sessions, login/session/logout/logout-all endpoints, migration0003, cookieOrigin/CSRF controls,
bearer compatibility, persistent login counters and the real responsive SvelteKit dashboard.
Screens/routes:login,projects list/create/detail,service create/configuration and session controls.
No public signup, deployment execution, customer containers or other excluded scope was added.

Initial clean checkpointcc202fd8f91e36b8aad86011e75cab7848d7f32d:
239 backend/engineering passes,19 failures; all16 real desktop/mobile journeys failed at login.
Formatting/unit/frontend/types passed;3 SQL-string lint findings. The common login failure was
Starlette cookie expiry receiving psycopg ZoneInfo rather than datetime.UTC. Static review also
found insecure cookies permitted for HTTPS origins outside production and raw pytest failure
tracebacks could contain disposable session material. Compose still asserted the old placeholder.
Initial raw failure diagnostics were kept private and never published.

One aggregate repair at3e50c363dda42b94d34a59450009c55e5ecb185a normalized UTC expiry, made all
HTTPS origins require Secure cookies, sanitized pytest output/JUnit without changing failures,
updated Compose to require an actual POST login form, and fixed lint. Exactly one clean local
full retest was performed:

| Check | Actual result |
| --- | --- |
| Backend + engineering |269 passed,0 failed/errors/skipped |
| Browser desktop1280x900 |6 passed,2 failed |
| Browser mobile390x844 |6 passed,2 failed |
| Browser total |16 executed,12 passed,4 failed,0 skipped |
| Ruff/format |Passed |
| Svelte/build/browser TypeScript |Passed;0 Svelte errors/warnings |
| Disposable Compose |Passed startup/HTTP/PostgreSQL/migrations/schema/nonroot/owned teardown |
| Evaluation catalog |9 passed,4 blocked,7 not_run; slice/phase unready |

The evaluator rejects the failed global browser artifact, so its zero *accepted* browser
observations must never be misreported as zero tests executed. Actual source-bound Playwright
results record16 executed. The12 passing journeys cover real project/service creation and
configuration persistence, invalid credentials/validation, tenant isolation, expiry, redirects,
keyboard navigation and responsive layout. Both logout scenarios failed on both viewports.
Their post-redirect replay/other-session assertions were not reached and are not claimed passed.

Root cause confirmed independently by frontend and security source review:
backend revocation commits, then Starlette delete_cookie emits `lava_session=""; Max-Age=0`.
The Svelte cookie parser interprets the quotes as a nonempty token, rejects it and returns503
before cookie clearing/redirect. Backend revocation tests pass; this does not prove an ongoing
access bypass, but broken logout UI/security control remains a merge blocker.

Future remediation needs separate authorization under the exhausted one-repair policy: safely
recognize empty/quoted-empty deletion cookies with Max-Age=0, preserve all existing cookie flags
and strict live-token validation, add direct cookie-parser coverage and rerun logout journeys.
No second repair was made, no assertion weakened and no failing branch merged.

The user subsequently authorized one exceptional, bounded repair and one full retest for this
specific logout-cookie failure. This exception is tracked separately in
`engineering/state/slice01.2.json`; it does not reset the original one-repair count or permit a
third repair if the exceptional retest fails. The repair validates an expired deletion header,
clears the cookie with matching attributes, and adds real-browser cookie-removal assertions.
The exceptional retest result will be recorded after execution.

Evidence SHA256:
- PostgreSQL JUnit:3d7e6ad4bd898fd44107865e053827a84eec4f730ffaa6799445091dc35b4e4e
- Browser JSON:0ea9af1d151e799e6f5743d47b3236ca28c0cd9356731eba3301572683474d03
- Browser JUnit:010eefb78a691d7949868ad2638383f3e550621f20dba46ba0641335144ad40d

Independent QA/security/user-simulation/architecture roles retained their exact scopes and
execution attribution. Primary coordinator executed tests; specialists reviewed source and
retained evidence. Trace/video capture stayed off; screenshots on failing session pages were
withheld. Only sanitized reports are eligible for Actions artifacts. Public TLS termination,
least-privilege runtime DB roles and recovery/email policies remain separate deployment limits.

Slice01.1's checkpoint had9 applicable passes and11 outstanding broader cases. Its prior
InstaBox success is historical evidence only, not a01.2 result. No01.2 InstaBox run is claimed:
feature code cannot access VM credentials, and blocked sources cannot qualify for protectedmain.
