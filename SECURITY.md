# Security

This development foundation is not ready for public Internet deployment. Slice01.1 adds
API bearer authentication and ownership checks; Slice01.2 adds server-managed browser sessions.
Keep API/frontend bound to loopback; use approved private access for a remote VM. PostgreSQL and Docker TCP APIs must never be publicly exposed.
Docker-group membership is effectively root access. The API image has no Docker SDK or socket.
Application containers run as non-root; PostgreSQL uses the upstream image's privilege handling.

Use environment-specific, least-privilege credentials. Bootstrap generates a random local
PostgreSQL password in an ignored .env with mode 0600. Templates contain no usable password.
Use URL-safe passwords for Compose database URLs. Production must separate the migration role
from the application's limited database role and use a managed secret store; the local developer
role intentionally owns the disposable database. Do not reuse it in production.

Settings redact database URLs. Readiness errors log an event without exception/credential text.
Do not log request bodies, authorization headers or environment dumps. Dependency locks are
committed; TLS and artifact checks remain enabled. Upgrade pinned dependencies deliberately.
Builds execute third-party package code; future untrusted builds require a separate sandbox and
worker identity. Never mount the host socket into untrusted application builds or the API.

Report vulnerabilities privately through the repository owner's GitHub contact/security channel.
Do not include credentials in issues. No security response SLA is promised at this stage.


Release verification hardens local secret creation with atomic exclusive mode-0600 writes.
The verifier captures only bounded, redacted command diagnostics, never environment dumps or
Docker inspect credential values. It checks exposure and privileges before starting services.
Disposable Compose projects have unguessable generated names; cleanup targets only that project.
Destructive migration tests require two explicit flags and a `*_test` database. The GitHub CI
service password is a test-only fixture for an isolated, loopback-bound runner database, not a
credential to any persistent environment. No administrative/destructive HTTP endpoint exists.
The development database owner remains intentionally broad; production role separation and
public authentication are still prerequisites before Internet exposure.

The InstaBox workflow accepts secrets only on trusted branch pushes/manual dispatch, never
pull_request_target. Its fixed API origin, no-redirect policy, free-tier guard, serialized
execution and exact-SHA Git bundle prevent credential forwarding, accidental billing, competing
runs and stale-source claims. Do not expand the API key beyond machines read/write for this
gate. Remote test execution intentionally runs trusted repository code; anyone who can push
those trusted branches must already be trusted to use the development VM. Resource cleanup
is limited to the newly allocated run's checkout, test DB and deterministic Compose project.

## Slice01.1 authentication and ownership

The project/service API now requires database-backed expiring/revocable bearer credentials;
public health/readiness remain credential-free. A client-supplied user identifier is never
accepted as authentication. Ownership is applied to all nested resource queries, including
updates/archives, with404 for inaccessible resources. Request validation errors are sanitized
rather than echoing submitted credentials. Body, query and authorization values are not logged.
Bearer tokens are OS-random, stored only as SHA256 digests, and issued once through a trusted
private CLI terminal. No passwords/cookies/browser sessions are implemented by this slice.
Do not use this boundary as evidence that future browser-session/CSRF/password requirements
have passed. See docs/adr/0001-control-plane-authentication.md for limitations and recovery.

Runtime DB access remains a development owner role; it can access metadata and is not suitable
for Internet production. Runtime/migration/provisioning privilege separation and TLS are release
prerequisites for public deployment. Archived records are retained; no HTTP administrative
credential issuance or destructive database/infrastructure endpoint exists. The quarantine
legacy user is disabled and must never receive working credentials.

## Slice01.2 browser sessions

Browser authentication now uses administratively provisioned Argon2id password accounts and
server-managed HttpOnly,SameSite sessions. Production settings fail closed without HTTPS and
Secure cookies. Password reset and logout-all revoke existing browser sessions, not independent
API credentials. ExactOrigin plus CSRF protect cookie mutations; login has Origin protection;
invalid Authorization does not fall back to a cookie. BFF routes are whitelisted and never
forward arbitrary identity/proxy headers. Login uses persistent account/peer counters and a
uniform unknown-user verification path. No public registration/recovery/default account exists.
See docs/adr/0002-browser-sessions.md for shared-peer throttling and remaining deployment limits.

Do not publish raw Playwright traces, recordings, network dumps or private fixture/server logs.
CI artifacts explicitly contain sanitized reports and verified masked screenshots only. No
infrastructure credential is provided to candidate application/browser tests. Actual InstaBox
verification uses the protected-main merge source after independent review and enforced CI.
