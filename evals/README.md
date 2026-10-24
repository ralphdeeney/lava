# Phase 01 acceptance evaluations

The six `.yaml` files use JSON syntax (a safe YAML subset) and define EVAL-001–020.
They are acceptance specifications, not an assertion that features exist. Phase 01 product
implementation is blocked on verified protected merge policy; all unexecuted scenarios remain
`not_run`, and the phase release score is zero until real evidence is supplied.

`python3 evals/runners/evaluate.py --output <report.json>` reconciles observations against the
current exact Git HEAD and exits nonzero unless every mandatory case passed. Missing, stale,
simulated and duplicate evidence cannot count as success. A passing fixture test of this
reconciler is a unit test of orchestration, not an executed Phase 01 acceptance scenario.

Observations contain id, source_commit, status, executed, simulated, evidence and reason.
Evidence must be independently reviewed, sanitized, exact-SHA runner/test artifacts. This
reconciler does not authenticate arbitrary observation files: it is an offline interface,
not a privileged merge authority. A future protected-main controller must verify provenance
and execute deterministic pytest/Playwright/VM adapters before supplying observations.
No mutable PR-supplied report may approve its own release or security review.

Browser acceptance must run real desktop/mobile journeys against SvelteKit plus PostgreSQL
with two disposable users. Never publish traces containing cookies/passwords/tokens; raw
Playwright traces require sanitization or restricted retention. Screenshots alone do not pass.
The existing trusted Phase 00 VM workflow is not authorization to run unreviewed PR code with
infrastructure secrets or Docker-root access on a credential-bearing persistent machine.
