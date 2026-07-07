# Contributing to mac-sysdash

Thanks for your interest! This is a small, deliberately-minimal project. The
constraints below are what keep it tiny and dependency-free — please read them
before opening a PR, so your change fits the grain of the project.

> Working with an AI coding agent? Point it at [`AGENTS.md`](AGENTS.md)
> (symlinked as `CLAUDE.md` / `GEMINI.md`) — it has the machine-oriented version
> of everything here.

## The one big idea

mac-sysdash is **one Python file + one HTML file**, no build step, no framework,
no cloud. A Mac serves its own stats over your LAN/Tailscale; several Macs show
each other's. That simplicity is the whole point — features are welcome as long
as they keep it.

## Hard constraints (please don't violate)

- **No new dependencies.** Backend: Python 3 **stdlib + `psutil` only**
  (`sqlite3` is fine — it's stdlib). Frontend: **zero JS dependencies.**
- **No build step, no framework.** `index.html` is served/opened as-is. Charts
  are hand-drawn SVG.
- **No external tools or services.** No Grafana/Prometheus/brokers/hosted DBs.
  Everything is shown **natively in the dashboard**.
- **Token-free & cross-machine.** Runner info is read from the runner's **local
  files**, never the GitHub API.
- **Runs as a launchd agent without Full Disk Access.** Never touch
  TCC-protected dirs (`~/Documents`, `~/Desktop`, `~/Downloads`, iCloud) on a hot
  path — wrap all filesystem access in `try/except`.
- **Keep `/api/stats` backward-compatible** — the client and peer machines depend
  on its shape.
- **Security:** the static file handler blocks path traversal
  (`fp.startswith(HERE)`) — keep it. No secrets in the repo.

## Non-goals

To set expectations before you invest time — these are out of scope on purpose:

- Authentication / multi-tenant / public-internet hardening (it's a trusted-LAN
  tool — see [`SECURITY.md`](SECURITY.md)).
- Cross-platform support beyond macOS.
- A packaged app, an installer GUI, or a JS build pipeline.
- Pulling data from the GitHub API, cloud dashboards, or external time-series
  databases.

Small, native, stdlib-only solutions beat feature-rich external ones here every
time.

## Dev setup

```bash
git clone https://github.com/berkayturanci/mac-sysdash.git
cd mac-sysdash
python3 -m venv venv && ./venv/bin/pip install psutil
```

**Run locally** (pick a free port; the real service uses 8765/8770):

```bash
SYSDASH_PORT=8799 ./venv/bin/python server.py
# then open http://localhost:8799
```

**UI only, no backend:** open `index.html?demo` in a browser — it loads sample
data with no server.

**Run the tests:**

```bash
./venv/bin/python -m unittest discover -s tests
```

Use the repo venv — it has `psutil`; the system `python3` may not.

## Style

- Match the existing **terse style**: small, focused helpers.
- Comments explain **why**, not what.
- Follow the patterns already in the file (error handling, naming, layout)
  rather than introducing new ones.

## Before you open a PR

1. **Tests pass** (`unittest discover -s tests`), and you added tests for new
   behavior where it makes sense.
2. For any **user-visible change**, bump `VERSION` in `server.py` **and** add a
   [`CHANGELOG.md`](CHANGELOG.md) entry ([SemVer](https://semver.org/)). Pure
   docs/meta changes don't need a bump.
3. Keep the diff focused — one logical change per PR.
4. If you changed the data model, confirm `/api/stats` stays
   backward-compatible.

Open an issue first if you're planning something large or unsure whether it fits
the constraints — it saves everyone time.

## Reporting bugs & ideas

Use the issue templates. For security issues, **don't** open a public issue —
follow [`SECURITY.md`](SECURITY.md).

By contributing, you agree that your contributions are licensed under the
project's [PolyForm Noncommercial License 1.0.0](LICENSE) — free for any
noncommercial use, no commercial use or resale.
