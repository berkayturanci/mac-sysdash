# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

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
