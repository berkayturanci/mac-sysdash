# Privacy

Short version: **mac-sysdash sends nothing to anyone.** There is no telemetry, no
analytics, no accounts, no cloud, and no phone-home. Everything stays on your own
machines and your own network.

## What it reads (locally)

To draw the dashboard, the server reads local system information on the machine
it runs on:

- **System metrics** via `psutil` and macOS APIs — CPU, memory, disk, swap,
  network rates, disk I/O, temperature/thermal state, battery, uptime, load.
- **Process list** — names, RSS, and CPU% of running processes (for the
  top-processes widget). Aggregated per app; no command-line arguments or file
  contents are read.
- **Self-hosted runner status** — read from the runner's **local files** only
  (`_diag/*.log`, `_work/_temp/_github_workflow/event.json`). This surfaces
  workflow/job name, PR number, branch, commit, and actor. **No GitHub API and
  no token are used.**
- **AI-assistant usage** (optional) — if [CodexBar](https://github.com/steipete)
  is installed, per-provider session/weekly counts are read from its local
  history files and (when readable) `widget-snapshot.json`. If the background
  `launchd` agent cannot read the snapshot, the optional **`codexbar` CLI** may
  fetch enabled providers instead. All best-effort and silently skipped if absent.

It deliberately **avoids TCC-protected folders** (`~/Documents`, `~/Desktop`,
`~/Downloads`, iCloud) on any hot path.

## What it stores (locally)

- A **SQLite database** at `~/.local/state/sysdash/history.db` holding
  per-minute metric averages (7-day retention), finished runner-job records,
  daily network totals (30-day retention), and dead-man check state.
- **Browser-side only:** your theme, language, pinned widgets, alert thresholds,
  and the recent-events log live in your browser's `localStorage`. They never
  leave your device.

Nothing is uploaded. To wipe stored history, delete the SQLite file and clear the
site's `localStorage`.

## What crosses the network

- **Only between your own machines.** In a multi-Mac setup, the hub pulls each
  peer's `/api/stats` (or peers POST to `/api/push`) over your LAN or
  [Tailscale](https://tailscale.com/) tailnet. This traffic contains the same
  system/runner stats shown in the dashboard.
- The browser talks only to the machine you point it at; the hub fetches peers
  **server-side**, so your browser makes no cross-origin calls.
- **No third parties** are ever contacted. The only outbound network call the
  server itself makes is an hourly `git fetch` against **your own** configured
  git remote to compute the "commits behind" badge — you can see and change that
  remote.

## Optional outbound you configure

If — and only if — you set them up yourself:

- An **alert webhook** (Settings → webhook) POSTs alert text to a URL you enter.
- **Dead-man checks** are pinged by *your* cron jobs hitting `/api/ping`.

Both are opt-in and go only where you point them.

## Summary

| | |
|---|---|
| Accounts / login | None |
| Telemetry / analytics | None |
| Third-party services | None |
| Data leaves your network | Only between your own machines (opt-in webhook aside) |
| Where data lives | Local SQLite + your browser's `localStorage` |
