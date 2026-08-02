# Security Policy

## Supported versions

Security fixes target the latest published release on the `main` line
(currently the `1.4.x` series). Older tags may not receive backports.

## Scope

Twin is a **local-first, single-user** cognitive layer. Typical trust
boundaries include:

- data under `$TWIN_HOME` (default `~/.twin`) — store, env, credentials;
- connector credentials and OAuth tokens;
- MCP / HTTP surfaces bound to the machine the user runs;
- optional at-rest encryption (`twin-cognition[crypto]`).

Twin is **not** a multi-tenant SaaS. Reports that assume shared hosting or
cross-tenant isolation are usually out of scope unless they affect the
local/single-user model.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Prefer one of:

1. GitHub **Private vulnerability reporting** on
   [caribeedu/twin](https://github.com/caribeedu/twin/security/advisories/new)
   (if enabled for the repository), or
2. Email the maintainer via the contact listed on the GitHub profile for
   [caribeedu](https://github.com/caribeedu).

Include:

- affected version / commit;
- reproduction steps or PoC (kept private);
- impact (data exposure, credential leak, remote code path, etc.).

You should receive an acknowledgement when the report is received. Please
allow reasonable time for a fix before public disclosure.

## Safe disclosure expectations

- Do not access other people's data or accounts.
- Do not run destructive tests against production systems you do not own.
- Prefer local reproduction against a disposable `$TWIN_HOME`.
