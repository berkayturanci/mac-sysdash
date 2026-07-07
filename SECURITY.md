# Security Policy

## Threat model — read this first

mac-sysdash is a **LAN / [Tailscale](https://tailscale.com/)-only dashboard**. By
design it:

- **Has no authentication and no accounts.** Anyone who can reach the port can
  read the stats it serves.
- **Serves system telemetry** (CPU/memory/disk, process names, network rates,
  self-hosted runner job metadata — PR/branch/commit/actor).
- **Binds to a plain-HTTP port** (default `8765`).

This is intentional and appropriate for its use case: a small fleet of your own
Macs on a private network you control. **It is not hardened for the public
internet.**

### Safe deployment

- **Do not** expose the port to the public internet or bind it to a
  public-facing interface.
- Keep it on `localhost`, a trusted LAN, or a [Tailscale](https://tailscale.com/)
  tailnet. If you need TLS, front it with `tailscale serve`.
- Treat everything the dashboard shows as visible to anyone on that network.

## What counts as a vulnerability

Because there is no auth by design, "the stats are readable without a password"
is **not** a vulnerability — that is the documented behavior. Things that *are*
security issues include:

- **Path traversal / arbitrary file read** beyond the served directory (the
  static handler enforces `fp.startswith(HERE)` — a bypass is a bug).
- **Remote code execution** or command injection from any request path.
- **A crash / hang** triggerable by an unauthenticated request (DoS).
- **Reading TCC-protected data** or anything outside the documented data sources.
- **Leaking secrets** (tokens, keys) — there should be none; the project is
  token-free and reads runner data from local files, never the GitHub API.

## Reporting a vulnerability

Please report privately — **do not open a public issue for security bugs.**

- **Preferred:** GitHub's [private vulnerability reporting][ghsa]
  (**Security → Report a vulnerability** on the repository).
- **Or email:** berkayturanci@gmail.com

Please include: what you observed, a minimal reproduction (request path / steps),
the affected version (`VERSION` in `server.py` or the header badge), and the
impact you think it has.

### What to expect

This is a small, single-maintainer hobby project maintained on a best-effort
basis. There is no SLA, but I aim to acknowledge reports within about a week.
Valid issues will be fixed in a patch release with credit in `CHANGELOG.md`
(unless you prefer to stay anonymous).

## Supported versions

Only the **latest release** is supported. Fixes ship on top of `main`; please
upgrade (`git pull --ff-only` + restart the agent) before reporting.

[ghsa]: https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability
