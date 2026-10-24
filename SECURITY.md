# Security

This development foundation is not ready for public Internet deployment. There is no user
authentication or authorization. Keep API/frontend bound to loopback; use SSH forwarding to
reach a remote VM. PostgreSQL and Docker TCP APIs must never be publicly exposed.
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
