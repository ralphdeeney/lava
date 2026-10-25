# Slice01.1 verification checkpoint

Scope: owned projects/services, authenticated API access, UUID metadata, safe archival and
PostgreSQL persistence. PR2 is merged; required checks are `engineering-controls` and `checks`
with strict enforcement and no bypass actors. No policy was changed for this slice.

The implementation checkpoint was225c3ce973c2783642d45c924e8e8b76aaa3a226. The first complete
PostgreSQL/engineering run produced197 passes/3 failures (partial resource PATCH and two lossy
legacy rollback cases), plus style findings. Unit/frontend/Compose checks passed. A reviewer
changed credential-safe test diagnostics after freeze, so the first run was explicitly not
accepted as clean-SHA evidence; its evaluation runner correctly blocked attribution.

One aggregate repair was committed at **d5e051183db62abc315ea6c11c16aff6506b73ee**. It merges
partial nested configuration, refuses rollback of edited legacy metadata, documents the actual
safe error envelope and formats tests/imports without removing assertions. Exactly one complete
local retest then passed:

- **203 tests passed, zero failures/skips**, including23 independent security cases.
- Ruff, formatting, Svelte checks (zero errors/warnings), production build passed.
- Disposable Compose startup, HTTP, PostgreSQL, repeated migrations, schema drift, non-root
  execution and owned-resource cleanup passed. Existing local services were preserved.
- **9/9 applicable deterministic evaluations passed**:003/004/005/006/009/012/013/016/017.
-11 remaining Phase01 cases are `not_run`; full-phase release readiness is **false**.

JUnit binds the real PostgreSQL run to that exact clean commit. SHA256:
`9fc2659948c756764cbaaf6f9d4a0c22b6212a67f6bb2e123dfb57da4a6b2978`.
Independent security/architecture specialists reviewed the implementation and repaired behavior;
security independently inspected all23 executed negative-case results and found zero scoped
merge-blocking issues. API-usability static retest resolved both contract findings. Test execution
was coordinated by the primary agent; reviewers do not claim they reran the tests.

The CI workflow generates fresh JUnit and evaluation JSON for its own exact checkout, publishes
both as Actions artifacts and repeats PostgreSQL/Compose verification in a clean runner. This
tracked checkpoint precedes PR publication; the PR and Actions are authoritative for the final
submitted SHA, required-check outcomes and actual merge state. Check
`gh pr view feat/phase01-slice01-control-plane --json url,state,mergeCommit,statusCheckRollup`.

The candidate was not run on a credential-bearing VM. Existing protected-main automation will
verify the independently reviewed squash-merge SHA on agent-development after merge. Do not
substitute historical/main-base results for this slice's VM evidence. A failed postmerge VM gate
blocks advancement. No manual SSH, storage relocation or persistent-resource deletion is used.

Bearer credentials require trusted local provisioning. Browser registration/cookie sessions,
environments, deployment metadata and browser journeys remain future scope. Public Internet
production also requires TLS and DB role separation. There is no persistent coding runner.
Do not start Slice01.2 until this slice is verified and actually merged; Phase02 remains excluded.
