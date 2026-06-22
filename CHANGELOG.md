# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

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
