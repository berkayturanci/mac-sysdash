---
title: "Extending mac-sysdash within its hard constraints (sampler → cache → stats, TCC traps, ship loop)"
date: 2026-06-30
category: best-practices
module: mac-sysdash
problem_type: best_practice
component: development_workflow
severity: medium
applies_when:
  - Adding any metric, widget, or endpoint to mac-sysdash (server.py / index.html)
  - A feature wants a new dependency, build step, framework, or external service
  - Reading host data that may live under a TCC-protected path on a launchd agent
  - "server.stats() / python server.py hangs but the live launchd service is fine"
  - Verifying a change locally before shipping (UI render, server fields, tests)
tags: [mac-sysdash, constraints, stdlib-only, psutil, tcc, launchd, sqlite, sampler, stats-cache, demo-mode, ship-loop, verification]
---

# Extending mac-sysdash within its hard constraints (sampler → cache → stats, TCC traps, ship loop)

## Context

mac-sysdash is deliberately tiny: one `server.py` (Python stdlib + `psutil`
only), one `index.html` (vanilla JS, no build step), `sqlite3` for persistence,
served by a per-user `launchd` agent and aggregated across Macs over Tailscale.
Across one long session it grew a lot — disk-fill ETA, flaky-job detection,
active-runs grouping, thermal/disk-I/O/load metrics, dead-man cron checks, webhook
+ native alerts, runner queue-pressure, per-interface net, daily bandwidth (v1.18
→ v1.24, ~12 issues) — **without adding a single dependency**.

The features were easy; staying inside the constraints while keeping each release
shippable and verified was the real work. This doc codifies the patterns and traps
so the next feature (by a human or an agent) inherits them instead of relearning.

---

## Guidance

### 1. The constraints are the product — treat them as non-negotiable

- **Server:** Python stdlib + `psutil` only. `sqlite3` is allowed (stdlib).
- **Client:** zero JS deps, no framework, no build step. `index.html` is served
  as-is; charts are hand-drawn SVG.
- **No external tools/services** (no Grafana/Prometheus/Docker/hosted DB) —
  everything renders natively in the dashboard. This is an explicit owner
  preference, not an oversight.
- **Token-free:** runner/CI data is read from the runner's *local* files
  (`event.json`, `_diag/Worker_*.log`), never the GitHub API.

Every feature in the roadmap had a stdlib/`psutil`/local-file path. Before
designing, find that path (`psutil.disk_io_counters()`, `pmset -g therm`,
`net_io_counters(pernic=True)`, a SQLite table). If a competitor feature has no
such path on macOS, it is out of scope — say so rather than reaching for a dep.

### 2. The data-flow pattern: background sampler → throttled cache → `/api/stats`

New metrics follow one shape:

1. A **background thread** samples (the 1s `_cpu_sampler`, or a slower dedicated
   thread for expensive/rare reads — `_thermal_sampler` at 30s, `_update_checker`
   hourly). HTTP handlers never sample inline.
2. State lives in a module-level dict (`_IO`, `_THERM`, `_NET_IF`) or a SQLite
   table; `stats()` only *reads* it.
3. `stats()` is wrapped by a **~0.8s cache** behind a lock so many concurrent
   pollers share one process scan.
4. Add the field to the `stats()` return and keep `/api/stats`
   **backward-compatible** — peers and the client depend on its shape.

For history/aggregates, add a table in `_init_db()` (idempotent
`CREATE TABLE IF NOT EXISTS`) and a read function. Examples added this way:
`checks` (dead-man), `net_daily` (bandwidth), plus `get_flaky_jobs`,
`get_queue_stats` over the existing `jobs` table.

### 3. TCC is the one thing that can hang you forever — guard every protected read

A `launchd` agent runs **without Full Disk Access**. Touching a TCC-protected path
(`~/Documents`, `~/Desktop`, `~/Downloads`, iCloud, `~/Library/Group Containers/…`)
on a hot path can **block indefinitely** on the consent gate. Rules:

- Keep `RUNNER_ROOTS` and any scanned dirs out of protected folders.
- Wrap every filesystem/sensor/subprocess read in `try/except` and give
  subprocess calls a `timeout=`.
- A best-effort read that *fails* must not discard a working fallback — e.g. the
  CodexBar snapshot read is wrapped so a `PermissionError` keeps the history-based
  AI fallback, and the optional `codexbar` CLI backfills other enabled providers
  off the hot path.

**The subtle trap (learned this session):** under `launchd` (no GUI session) the
TCC gate *denies fast* → `PermissionError` → fallback. But running
`python server.py` **interactively** in a terminal, the same read can pop a
consent **dialog** and block until someone clicks it — so `server.stats()` /
`--status` "hangs" even though the live service is perfectly healthy. If a
standalone run hangs, suspect a TCC-protected read, not your new code. (Tracked
fix: time-out-guard the snapshot read.)

### 4. Know your data semantics before you compute on it

- Disk/mem are reported as `total − free` / `total − available` (matches Finder
  Storage / Activity Monitor), **not** psutil's `used`.
- In the `jobs` table, `ts` is the job's **end** (Worker-log mtime); the **start**
  is `ts − duration`. The queue-pressure feature depends on this — getting it
  backwards inverts the contention math.
- Self-hosted runners are **serial** (one Worker at a time), so "overlap" is rare;
  real queueing shows up as back-to-back starts (next job begins within seconds of
  the previous end). Validate such assumptions against real timestamps.

### 5. Verify the way it actually runs, and ship in small slices

- **UI:** open `index.html?demo` (loads `DEMO_A`/`DEMO_B` with no backend) and
  keep the demo data current when you add a `stats` field — it's how you preview
  and screenshot without a live host.
- **Server fields:** the most representative check is hitting `/api/stats` on a
  running instance; remember the ~0.8s cache (poll twice / wait >1s before
  asserting a just-written value).
- **Tests:** `./venv/bin/python -m unittest discover -s tests`. If the suite
  hangs on the AI/TCC read in this environment, neutralize it for the run by
  pointing `server._CODEXBAR_SNAPSHOT` / `_CODEXBAR_HISTORY` at nonexistent paths.
- **JS sanity** without a browser: extract `<script>` blocks and
  `vm.compileFunction` them under Node.
- **Per release:** bump `VERSION` in `server.py` + add a `CHANGELOG.md` entry
  (SemVer), branch → PR → rebase-merge → `git pull --ff-only` +
  `launchctl kickstart -k gui/$(id -u)/com.berkay.sysdash` on each Mac. `index.html`
  needs no restart (served fresh, `sw.js` is network-first); `server.py` does.
  Pure docs/meta changes skip the version bump.

## Why This Matters

The dashboard's whole value proposition is "self-contained, token-free, runs
anywhere a Mac does, no infra." A single dependency, build step, or external
service breaks that promise and the cross-machine deploy story. The sampler→cache
pattern keeps it responsive under many viewers; the TCC discipline is the
difference between a rock-solid agent and one that mysteriously wedges. Shipping in
small verified slices (each its own version + CHANGELOG + deploy) is what let ~12
features land back-to-back without a regression.

## When to Apply

- Designing any new metric/widget/endpoint — start from "what's the stdlib /
  `psutil` / local-file source?" and the sampler→cache→stats shape.
- Any code reading host state that might be TCC-protected, or any "works as a
  service but hangs when run by hand" report.
- Before each ship: demo-preview the UI, test with AI paths neutralized, bump
  VERSION + CHANGELOG, deploy + verify live.

## Examples

- **Add a metric (disk I/O):** sample `psutil.disk_io_counters()` deltas in
  `_cpu_sampler` → `_IO` dict + `hist.disk_read/disk_write` → `stats.io` → SVG
  sparkline in the system card → extend `DEMO_*`.
- **Add an aggregate (flaky / queue):** pure SQL over `jobs` in a `get_*` function
  → `stats` field keyed by runner dir → render in the runner modal. No new table.
- **Add persistence (dead-man checks / daily bandwidth):** `CREATE TABLE IF NOT
  EXISTS` in `_init_db` → write path (an endpoint or the per-minute flush) → read
  function → `stats` field → UI strip.
- **Rare/expensive read (thermal):** dedicated 30s thread shelling `pmset -g therm`
  with `timeout=`, parsed into `_THERM`; the UI chip only shows when throttled.

## Related

- `AGENTS.md` (= `CLAUDE.md` / `GEMINI.md`) — hard constraints, `/api/stats` data
  model, gotchas.
- `CHANGELOG.md` — the v1.18–1.24 roadmap entries this learning generalizes.
- `README.md` — user-facing feature docs, dead-man-check wiring, multi-machine setup.
