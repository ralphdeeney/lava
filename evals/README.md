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
