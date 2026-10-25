# ADR0002: Server-managed browser sessions and a same-origin dashboard

Status: accepted for Slice01.2. Supersedes ADR0001's deferral of browser authentication;
its bearer API token design is retained.

A trusted local administrator provisions/reset passwords with
`python -m lava.auth.accounts provision USERNAME` (getpass confirmation), or the explicit
`--password-stdin` option for a secure automation channel. No public signup/default account,
password argument, password echo, recovery/email system or browser token provisioning exists.
Passwords are12–1024characters and hashed with pinned Argon2id (64MiB,3iterations,4lanes).
Reset atomically revokes all existing browser sessions; it intentionally preserves independent
API tokens, which require their separate existing revocation operation.

FastAPI owns session issuance, lookup, expiry and revocation in PostgreSQL. Each login issues
fresh OS-random32byte opaque session material, stores only its SHA256 digest, and revokes a
previous session cookie when present. Login/session JSON returns user metadata, expiry and a
session-bound CSRF token; it never returns the session identifier. Cookies are host-only,
HttpOnly,SameSite=Lax,Path=/,with bounded Max-Age. Secure cookies and an HTTPS browser origin are
mandatory for every HTTPS origin, in all environments; production additionally requires HTTPS.
Local loopback development explicitly permits HTTP.
Session lifetime defaults1hour, configurable60seconds–24hours. GET/session and every protected
operation check expiry, revocation and active identity server-side. Logout clears the cookie
and invalidates the server record. Logout-all revokes all browser sessions for the principal.
No JWT or browser localStorage credentials are used.

The SvelteKit server is a narrow same-origin backend-for-frontend. A private validated
LAVA_API_ORIGIN selects the internal FastAPI endpoint, never browser/public configuration.
Its proxy permits only explicit auth/project/service routes and methods, forwards only the
session cookie and required request headers, and does not forward bearer/client identity or
arbitrary proxy headers. SSR revalidates authentication for protected screens. Login redirects
are constrained to known relative application paths. Authenticated HTML/API/actions/errors
use private,no-store cache semantics. Password inputs are never returned in action data.

Cookie-authenticated mutations require BOTH the exact configured browser Origin and
X-CSRF-Token. The CSRF value is SHA256('csrf:'+raw_session), returned by authenticated same-origin
session retrieval and compared in constant time. Login also requires exact Origin to mitigate
login CSRF. SameSite is defense in depth, not the only CSRF control. Bearer requests remain
cookie-independent; if Authorization is present but invalid, authentication fails instead of
falling back to a cookie. Infrastructure operations remain outside all public API processes.

Login counters persist in PostgreSQL using atomic upserts, bounded stale-row cleanup and
hashed account/actual-peer keys:5attempts/account+peer and50attempts/peer per15minutes. Successful
attempts also count. Unknown-user passwords use a dummy Argon2 verification and generic errors.
Forwarded IP headers are not trusted. In the BFF topology the upstream peer is shared by the
web server, so the50limit is dashboard-wide; future scale needs explicitly trusted proxy
identity design rather than accepting spoofable client headers.

Migration0003 adds password accounts, browser sessions and counters with FK/expiry integrity
and expiry indexes. Existing users/projects/services/API tokens survive. Downgrade refuses to
drop password/session/counter data; no automatic destructive reset or schema rollback exists.
Future maintenance should expire/reap historical session rows through a reviewed bounded task.

Real browser tests use two random disposable accounts with private0600 fixtures. Trace/video
capture is OFF because network/session/password data would leak; only sanitized named outcomes
and safely masked screenshots are publishable. Test-only expiry/throttle fixture operations
require acknowledged *_test PostgreSQL and owned identities; there is no HTTP testing backdoor.
Public deployment still requires TLS termination, correct explicit origins, limited runtime DB
privileges and account lifecycle/recovery policies. This slice does not declare those complete.
