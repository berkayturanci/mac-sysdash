# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [1.10.1] - 2026-06-26

### Fixed
- **UI render crash:** Fixed a JavaScript SyntaxError caused by duplicate variable declarations that broke the rendering loop.
## [1.10.0] - 2026-06-26

### Added
- **Fleet Overview Banner.** A new sticky strip at the top of the dashboard displays total online machines, and the aggregate count of busy, idle, and offline runners across the fleet.
- **Top Processes Toggle.** Added a segmented control to the "Top Processes" card, allowing the list to be toggled between memory usage (the old default) and CPU usage (new). `server.py` now queries both.
- **Visual Improvements for Gauges.**
  - **Memory and Disk sparklines.** The system gauges now draw sparklines below the ring charts for Memory and Disk, matching the CPU gauge.
  - **Network throughput sparkline.** A dual-colored (green/blue) sparkline now tracks download/upload history inside the System card.
  - **Load average and Swap usage bars.** Added miniature proportion bars for load (turns amber > 1, red > 2 per core) and swap usage.


## [1.9.1] - 2026-06-26

### Changed
- **Runner detail modal redesign.** The job-stats section is now an aligned
  table (Job · Runs · Success · Median) with a colour-coded success bar (red /
  amber / green), preceded by a summary strip (total runs · overall success ·
  failed count). Recent-run rows split onto three lines — **job**, `⚙ workflow`,
  and `PR · branch` — with tightened line spacing, and the "Recent runs" heading
  gained breathing room above it.
- **Durations under a minute now show seconds** (`12s`) instead of collapsing to
  `0m`/`~0d`, in both the job-stats medians and the recent-run list.
- The modal now **scrolls when its content is taller than the viewport** — a long
  history no longer clips the title or the footer links.

### Fixed
- CLI `--status` no longer prints a `BrokenPipeError` traceback when piped (e.g.
  `--json | head`); it now exits quietly like a normal Unix tool.

[1.9.1]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.9.1

## [1.9.0] - 2026-06-26

### Added
- **Long-term metrics history** — per-minute CPU/RAM/disk averages are persisted
  to a local SQLite DB (`~/.local/state/sysdash/history.db`, pruned to 7 days);
  the chart gains **1h / 24h / 7d** ranges next to the live 5m view, served from
  a new `/api/history?range=…` endpoint. (#3)
- **Per-job stats** in the runner detail modal — run count, success rate, and
  median duration per job, from the existing history. (#4)
- **CLI status mode** — `python server.py --status [URL]` prints runner + system
  status as a table (`--json` for raw output, ANSI auto-disabled off a TTY). (#5)
- **Runner alerts** — a runner going offline (after being seen online) or a job
  stuck busy for >30 min now raises the same banner/notification as the ≥95%
  system alerts. (#6)

### Fixed
- `server.py` was missing `import sys`, which the new CLI / `__main__` path
  references at startup — without it the server failed to start at all. Added a
  subprocess regression test that exercises the `--status` path.

[1.9.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.9.0

## [1.8.1] - 2026-06-26

### Fixed
- Runner detail modal: recent-run rows no longer truncate the workflow far too
  early. The text column was capped at a fixed `max-width`, leaving a big empty
  gap before the result/duration; it now fills the available width and wraps to
  two lines — **job** on top, `⚙ workflow · branch` beneath — each ellipsizing
  only when it genuinely overflows.

[1.8.1]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.8.1

## [1.8.0] - 2026-06-25

### Fixed
- Runner cards and run history now show the **specific job** a runner executed
  (e.g. `Build Android APKs`, `Test & Lint`) instead of only the workflow. A
  multi-job workflow split across runners previously rendered the *same*
  `workflow · PR` on every participating runner, hiding which job each one
  actually ran. The job's display name is read locally from the runner's newest
  `_diag/Worker_*.log` (one per job) — `event.json` is the shared workflow
  trigger and carries no per-job identity.

[1.8.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.8.0

## [1.7.1] - 2026-06-23

### Added
- Recent-run history now also parses the **actor** (who triggered) and the PR's
  real **head branch** from the runner logs; the run tooltip shows
  `workflow · branch (head) · result · duration · date · 👤 actor`.

[1.7.1]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.7.1

## [1.7.0] - 2026-06-23

### Added
- **Night theme** — a dimmed, desaturated, motion-free mode for working late
  (theme toggle now cycles auto → light → dark → night).
- **Runner filter** — show all runners or only the active (busy) ones.
- **Chart hover crosshair** — hovering the time-series chart shows the value and
  how long ago at the cursor.
- **Runner history tooltips** — each recent run shows full workflow · branch/PR ·
  result · duration · exact date-time on hover.
- Footer credit.

[1.7.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.7.0

## [1.6.0] - 2026-06-22

### Added
- **Stale indicator:** a pushed peer that stops updating shows an amber "stale ·
  Ns" pill and dims, instead of silently freezing, before it drops off.
- **Disk sparkline + chart** for consistency with CPU and memory (disk history is
  now sampled too).
- Tests for the push/proxy paths (`/api/push`, `/api/peer?key=`, peer listing and
  expiry) and a disk-history check.

### Changed
- Removed the manual "＋ machine" host bar — peers are fully handled by pull
  discovery and push, so it's no longer needed.

### Docs
- Security note: the dashboard is unauthenticated and meant for a private tailnet
  (don't expose via Funnel). Added a dark-mode screenshot.

[1.6.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.6.0

## [1.5.2] - 2026-06-22

### Changed
- Push interval lowered to 0.5s so pushed peers feel live.
- Battery shows a low-battery icon (🪫) when unplugged and ≤20% (red text), with
  amber text ≤40%.

[1.5.2]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.5.2

## [1.5.1] - 2026-06-22

### Changed
- Push every 1s (was 3s) so pushed peers update at the dashboard cadence.

[1.5.1]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.5.1

## [1.5.0] - 2026-06-22

### Added
- **Push mode** (`SYSDASH_PUSH_TO`): a machine that can't accept inbound
  connections POSTs its stats to a hub's new `/api/push` endpoint and appears on
  the hub like any other peer. Opt-in; coexists with pull discovery.

[1.5.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.5.0

## [1.4.0] - 2026-06-22

### Changed
- **Server-side peer aggregation:** the browser fetches peers through the hub's
  `/api/peer` proxy instead of contacting each peer directly. Removes HTTPS
  mixed-content limits and works on phones that can only reach the hub.

[1.4.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.4.0

## [1.3.3] - 2026-06-22

### Fixed
- Multi-machine over HTTPS: when the page is served over HTTPS, peers are now
  probed at their Tailscale HTTPS name (`https://<host>.<tailnet>.ts.net`) instead
  of `http://<ip>:8765`, which browsers block as mixed content. Each peer must run
  `./serve.sh` to be reachable over HTTPS.

### Changed
- Mobile header: clock moves to the top-left on its own line above the buttons.

[1.3.3]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.3.3

## [1.3.2] - 2026-06-22

### Fixed
- Mobile layout: gauges use `minmax(0,1fr)` so the three rings shrink to fit
  narrow screens (no more clipped Disk gauge); rings are now fluid, the machine
  header wraps, and panels stack full-width on phones.

[1.3.2]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.3.2

## [1.3.1] - 2026-06-22

### Added
- A `unittest` test suite (`tests/`) covering parsing, stats invariants, peer
  discovery, battery, and HTTP routes. Run locally with
  `python3 -m unittest discover -s tests`.

### Fixed
- Runner job result is now read correctly from short Worker logs (the result line
  could be missed when the whole log fit in the head read).

[1.3.1]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.3.1

## [1.3.0] - 2026-06-22

### Added
- Click a runner to open a **detail modal**: the current job plus the last 5 runs
  with workflow, branch (PR # for pull-request runs), result, duration and "ago",
  each linking to that workflow's runs on GitHub, plus Actions / runner-settings
  shortcuts. Job history now carries the workflow and branch per run.

### Changed
- Clearer notification toggle: the bell turns accent-colored when on, with a
  confirmation notification and an HTTPS hint when permission is blocked.

### Fixed
- Silence `BrokenPipeError` tracebacks from clients disconnecting mid-response.

[1.3.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.3.0

## [1.2.0] - 2026-06-22

### Added
- Auto-discovery of tailnet peers running mac-sysdash — reachable machines appear
  automatically, no manual add.
- Drag a machine panel by its header to reorder; order is persisted.
- Collapsible sections (Runner status / System / Top processes) to keep just the
  gauges in view.
- Recent-job history dots per runner (green = succeeded, red = failed), parsed from
  the runner's `_diag` logs.
- Click a CPU/memory gauge for a larger ~5-minute time-series chart.
- Desktop/phone notifications when a metric goes critical, plus `serve.sh` to expose
  the dashboard over HTTPS via Tailscale Serve (required for notifications).
- `?theme=light|dark` URL override for sharing/screenshots.
- New activity-pulse app icon and crisp SVG favicon.

### Changed
- Machines fill the available width and wrap down; a lone panel's content is capped.
- Dark-mode text softened to reduce glare on the large gauge numbers.

[1.2.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.2.0

## [1.1.0] - 2026-06-22

### Added
- Battery (percent / charging / time left) and live network throughput (↓/↑).
- 60-second CPU and memory sparklines under the gauges.
- Per-busy-runner job runtime (elapsed since the job started).
- Per-machine local time with timezone in each panel header.
- Progressive Web App: manifest, service worker, and icons — installable to the
  home screen for a full-screen, app-like view.
- 24-hour clock by default, click to toggle 12h/24h.
- `?demo` mode rendering brandless sample data (used for the screenshot).

### Changed
- Disk usage now measured as `total − free` on the APFS data volume, and memory
  as `total − available`, so percentages match Finder Storage and Activity
  Monitor (the figure and the GB text now share one basis).
- Critical (red) alert threshold raised from 90% to 95%.
- Header shows a single viewer clock; redundant timestamp removed.

[1.1.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.1.0

## [1.0.0] - 2026-06-22

First public release.

### Added
- System dashboard with CPU / memory / disk ring gauges, per-core bars, load
  average, swap, uptime, and the top memory-consuming processes.
- GitHub Actions self-hosted runner panel with live `busy` / `idle` / `offline`
  status, auto-discovered from `~/GitHub` and from running runner processes.
- Per-busy-runner job context (branch, workflow, PR / issue, commit, actor) read
  locally from the runner's event payload — no GitHub token required. Cards link
  to the PR when building one, and reveal truncated detail on hover.
- Multiple machines shown side by side; peers added from the UI by address with
  automatic `:8765` port completion and hostname-based naming.
- High-usage alerts at ≥95% (gauge badge, banner, and browser tab-title prefix).
- Light / dark / auto theme following the system appearance.
- English / Turkish UI defaulting to the system language, with a selector.
- `install.sh` / `uninstall.sh` managing a per-user `launchd` agent that starts
  at login and self-restarts; `psutil` is provisioned into an isolated venv when
  no suitable interpreter is found.

### Notes
- Disk usage is measured on the APFS data volume as `total − free`, and memory as
  `total − available`, so the reported percentages match Finder's Storage and
  Activity Monitor.

[1.0.0]: https://github.com/berkayturanci/mac-sysdash/releases/tag/v1.0.0
