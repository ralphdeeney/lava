# ADR0001: Scoped administrative API credentials

Status: accepted for Slice01.1; browser account/session flows remain deferred.

There is no existing authentication implementation. The first control-plane API uses opaque
bearer credentials provisioned through a trusted local CLI with database access. No caller
can choose its identity through a header, query parameter or JSON owner field. Each credential
resolves to an active persistent user; project ownership is checked on every project/service
operation. Resource IDs alone grant no access. Missing, invalid, expired and revoked tokens
receive the same401; inaccessible resources receive404.

Credentials contain at least256 bits of OS-generated randomness. Only SHA256 digests are
stored. Fast token hashing is appropriate for random high-entropy credentials; it is not an
acceptable substitute for password hashing. There are no passwords, cookies, browser storage,
public signup or login endpoints in this slice. Cookie session/CSRF controls, password hashing,
login throttling, account recovery and email verification belong to future browser-auth work.
Bearer API clients must use TLS outside local loopback; do not expose this developer foundation
publicly. Keep credentials in a secure client credential store, never URLs or committed files.

The CLI prints a newly issued credential once to its invoking administrator. Run it only in a
private terminal, never a CI job, published diagnostic log or shell tracing session. The token
is never a command-line argument. Expiry is bounded and revocation is persisted. Possession of
the administrative database role is required to provision identities; no administrative HTTP
endpoint can mint users or credentials. Production requires a separate least-privilege runtime
DB role and scoped migration/provisioning access before public deployment.

Projects/services use reversible archival, not infrastructure deletion. No Docker, volumes,
builds, routing or customer containers are controlled by these APIs. Archived names remain
reserved to prevent accidental name takeover. Existing Phase00 projects have no provable owner:
migration preserves them under a disabled quarantine identity rather than granting arbitrary
users ownership. Recovery/reassignment requires reviewed administrative database work; no public
claim endpoint is provided. Unsafe destructive downgrades must stop rather than lose owned data.
