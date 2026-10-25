# Phase01 acceptance evaluations

The six JSON-subset YAML catalogs define EVAL001–020. At the **Slice01.1 checkpoint**,9
applicable scenarios passed and11 broader scenarios were outstanding; the phase score was
not zero. See docs/verification/phase01-slice01.md and PR3 merge2c78551. Do not confuse
historical checkpoint results with current-source evidence.

`evals/runners/control_plane.py` preserves Slice01.1 reconciliation. The browser-auth runner
adds provisioned-account authentication (public self-registration is not required by01.2),
bad-login rejection, real browser project creation and logout invalidation, while additionally
requiring expiry/revocation/CSRF/cookie/rate-limit negative tests. It consumes exact-source
real-PostgreSQL JUnit and sanitized real desktop/mobile Playwright results. All required
browser scenarios, both viewports and security assertions must pass; failed/skipped/dirty,
stale, malformed or simulated evidence cannot qualify a slice. The full phase remains
unready while environment/deployment/remaining scenarios have not executed.

`python3 evals/runners/evaluate.py --output <report.json>` is the generic full-phase offline
reconciler. It requires all mandatory cases, not just the subset authorized by one slice.
Parser unit fixtures are synthetic tests of reconciliation, never product acceptance evidence.
Neither offline runner authenticates arbitrary caller-provided XML/JSON or acts as a privileged
merge authority; independently reviewed actual Actions/test artifacts and enforced checks are
required. No PR-supplied report can grant itself infrastructure access or security approval.

The browser verifier starts actual production SvelteKit and FastAPI processes against real
PostgreSQL, provisions two random accounts, runs desktop/mobile journeys and cleans ownedrows.
Passwords/session IDs are never included in public outcomes. Raw traces/videos are disabled;
private local diagnostics are excluded from Actions artifacts. Screenshots are withheld when
credential checks fail and mask input fields. Screenshots alone cannot pass an evaluation.
The trusted-main InstaBox workflow verifies only reviewed merged sources, never untrusted PR
checkout code with infrastructure credentials. Report that exact merge SHA separately.

## Slice 01.3 membership and environment evaluation

`evals/runners/tenancy.py` extends the previous source-bound reconciliation with real
PostgreSQL assertions for project-scoped environment uniqueness/isolation (EVAL-007) and
Railpack-preference service metadata (EVAL-008). It requires all 26 fixed browser outcomes
(13 named journeys in both desktop and mobile viewports), including invitations, role changes,
revocation, read-only access and archived environment behavior. Four named backend tenancy
security guards for immediate revocation, final-owner protection, role escalation and
single-use/expired/revoked invitations must also pass. Missing, failed, skipped, dirty, stale,
unknown or simulated evidence blocks Slice 01.3. Parser unit fixtures are synthetic and are
never reported as actual browser execution.

The catalog still has 20 mandatory Phase 01 scenarios. When all applicable Slice 01.3
evidence passes, its scoped score is **15 applicable passes**: the 13 established cases plus
EVAL-007 and EVAL-008. EVAL-010 and EVAL-011 require future deployment metadata. EVAL-018
requires exact-source fresh-machine/Compose evidence, EVAL-019 a real PostgreSQL-outage
readiness assertion, and EVAL-020 scoped cleanup evidence. Those five remain `not_run` in
the offline tenancy report unless separate exact-source executed evidence is reconciled;
workflow definitions or historical VM runs do not count as a pass. The full Phase 01 release
remains unready while any mandatory case has no evidence.

The browser verifier provisions five random disposable users in a dedicated acknowledged
`*_test` PostgreSQL database and deletes only their owned projects, memberships, invitations,
environments, services, credentials and sessions. No invitation token or account credential is
published in sanitized reports. Existing 16 Slice 01.2 browser outcomes remain required.
