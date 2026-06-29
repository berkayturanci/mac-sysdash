# Agent guide — mac-sysdash

Context for AI coding agents working in this repo. Human-facing docs live in
`README.md`; release notes in `CHANGELOG.md`. (`CLAUDE.md` and `GEMINI.md` are
symlinks to this file.)

## What this is

A tiny, self-contained system + GitHub Actions **self-hosted runner** dashboard
for Macs. One Python file serves a JSON API and a single static page; several
Macs show each other's stats over Tailscale. No accounts, no GitHub token, no
database server, no cloud.

## Files

- `server.py` — the whole backend. Python 3, **stdlib + `psutil` only**.
  Background sampler, `/api/stats` JSON, peer pull/push aggregation, static file
  serving. Runs as a launchd agent.
- `index.html` — the whole frontend. **Vanilla JS, no build step, no
  dependencies.** Charts are hand-drawn SVG. The `?demo` query param loads
  sample data (`DEMO_A`/`DEMO_B`) with no backend.
- `tests/test_server.py` — `unittest` suite (config/log parsing, stats
  invariants, HTTP routes, peer discovery).
- `sw.js` — service worker (network-first; caches the app shell for offline).
- `install.sh` / `serve.sh` / `uninstall.sh` — launchd-agent setup + venv
  bootstrap.

## Hard constraints (do not violate)

- **No new dependencies.** Server: stdlib + `psutil` only. Client: zero JS
  dependencies. `sqlite3` is acceptable (it is stdlib).
- **No build step and no framework** for `index.html`. It is served/opened as-is.
- **No external tools or services.** No Grafana, Prometheus, message brokers,
  hosted DBs, etc. Everything is shown **natively in the dashboard**. This is an
  explicit owner preference — prefer in-app, stdlib-only solutions.
- **Token-free & cross-machine.** Runner info is read from the runner's **local
  files**, never the GitHub API.
- **Runs as a launchd agent without Full Disk Access.** Never touch
  TCC-protected dirs (`~/Documents`, `~/Desktop`, `~/Downloads`, iCloud) on a hot
  path — it can block forever. Wrap all filesystem access in `try/except` (follow
  the existing patterns).
- Match the existing **terse style**: small focused helpers; comments explain
  *why*, not *what*.

## Run / test / preview

- **Tests:** `./venv/bin/python -m unittest discover -s tests`
  (use the repo venv — it has `psutil`; the system `python3` may not).
- **Run locally:** `SYSDASH_PORT=8799 ./venv/bin/python server.py`, then open
  `http://localhost:8799`. (The real service uses 8765/8770; pick a free port.)
- **UI only, no backend:** open `index.html?demo`.

## Conventions

- Bump `VERSION` in `server.py` **and** add a `CHANGELOG.md` entry for every
  user-visible change (SemVer). Pure docs/meta changes (like this file) don't
  need a version bump.
- Keep `/api/stats` backward-compatible — the client and peer machines depend on
  its shape.
- Security: the static file handler blocks path traversal (`fp.startswith(HERE)`)
  — keep it. No secrets in the repo.

## Data model (`/api/stats`, server → client)

`{version, host, localtime, tz, cpu, mem, disk, disk_eta_days, swap, net, io,
thermal, battery, hist, runners[], jobs_summary, flaky, checks, update_behind,
queue, top[], top_cpu[], ai, uptime, ...}`

- `hist` is ~5 min of per-second samples for the sparklines/chart:
  `{cpu[], mem[], disk[], net_down[], net_up[], disk_read[], disk_write[], load[]}`.
- `io` is disk throughput `{read, write}` bytes/sec (`psutil.disk_io_counters()`
  deltas). `thermal` is `{state: nominal|fair|serious|critical, cpu_limit}` from
  `pmset -g therm` (unprivileged, background thread); the header shows a 🌡 chip
  only when throttled. Both are best-effort and default to safe values.
- `top[]` / `top_cpu[]` are top processes by RSS / CPU%.
- `ai` is AI-assistant usage per provider, read locally from CodexBar:
  `~/Library/Application Support/com.steipete.codexbar/history/{claude,codex}.json`
  (the launchd-safe fallback) plus the richer `…/Group Containers/…/widget-snapshot.json`
  (TCC-blocked under launchd). The snapshot read MUST stay best-effort so a
  PermissionError doesn't discard the fallback. Shape: `{provider: {session, weekly}}`.
- `jobs_summary` is `{runner_dir: {"YYYY-MM-DD": {succeeded, failed, other}}}`
  (UTC dates) — feeds the per-runner 30-day CI health heatmap in the modal.
- `flaky` is `{runner_dir: [{job, runs, fails, fail_rate}]}` — jobs that both
  pass and fail over 14 days (10–90% fail rate, ≥3 runs); shown in the modal.
- `checks` is `[{name, last_seen, ago, period, grace, state}]` — dead-man checks
  (`state`: up → late → down). Cron jobs register/refresh via
  `GET /api/ping?job=<name>&period=<sec>&grace=<sec>` on success (stored in the
  `checks` SQLite table). Late/down checks raise the client alert pipeline **and**
  a server-side native `osascript` notification (deduped until recovery).
- `queue` is `{runner_dir: {jobs, overlaps, back_to_back, wait_secs, pressure}}`
  — contention from the jobs table (`ts` = job end, start = ts−duration). On
  serial runners a job starting within 45s of the previous end was queued; shown
  as a "Queue pressure" bar in the runner modal.
- `disk_eta_days` is days-to-full from the 24h disk%-slope (or null); the disk
  gauge shows `⏳~Nd`. `update_behind` is commits behind `origin/main` (hourly
  background `git fetch`; header badge), 0 when current/offline.

Each `runners[]` item: `{name, repo, dir, status: 'busy'|'idle'|'offline',
uptime, url, history[], job?}`.

- `status` is derived from running `Runner.Listener` / `Runner.Worker` processes.
- For a **busy** runner, `job` is local context: PR / branch / commit / actor
  from `_work/_temp/_github_workflow/event.json` (the workflow **trigger**,
  shared by every job in a run) **plus** `job.name` — the specific job —
  read from the newest `_diag/Worker_*.log` (`"jobDisplayName"`). event.json has
  no per-job identity; the Worker log does. One workflow can split its jobs
  across several runners.
- `history[]` are recent finished jobs, one per Worker log:
  `{result, dur, ago, workflow, job, branch, actor, head}`.

Persistence: a background thread keeps a SQLite DB at
`~/.local/state/sysdash/history.db` — `hist` (per-minute cpu/mem/disk averages,
7-day retention; served at `/api/history?range=1h|24h|7d`) and `jobs` (finished
runner jobs, PK `(runner, logfile)`, deduped; feeds `jobs_summary` and the modal
Gantt timeline via `/api/jobs`). `sqlite3` is stdlib, so this is allowed.

Endpoints: `/api/peers` lists reachable machines; `/api/peer?key=…` proxies one
peer's stats and `/api/peer_jobs` its jobs (the hub fetches peers server-side so
the browser makes no cross-origin calls). Machines that can't accept inbound
connections POST to `/api/push`. CLI: `python server.py --status [URL]` prints a
text table (`--json` for raw).

UI (index.html): ring gauges + sparklines, fleet overview banner, per-machine
collapse + global widget pinning (★), runner cards + a detail modal (job-stats
table, 30-day health heatmap, Gantt timeline, recent runs), an AI-usage widget,
light/dark/night themes, EN/TR.

## Deploy (FYI — usually not the agent's job)

Runs as launchd agent `com.berkay.sysdash` from this checkout on `main`.
Deploy = land on `main`, then on each Mac:
`git pull --ff-only` + `launchctl kickstart -k gui/$(id -u)/com.berkay.sysdash`.
`index.html` changes need no restart (served fresh); `server.py` changes do.

## Gotchas

- Disk/mem report `total - free` / `total - available` (matches macOS
  Storage / Activity Monitor), **not** psutil's `used`.
- `sw.js` is network-first, so a new `index.html` reaches users on reload without
  a cache-version bump.
- Stats are cached ~0.8 s behind a lock so many concurrent viewers share one
  process scan instead of each triggering its own.
