## [1.34.0] - 2026-07-07
### Added
- **Marketing website** at <https://berkayturanci.github.io/mac-sysdash/> — an
  Astro site under `site/` (with SEO: canonical, Open Graph, JSON-LD, sitemap,
  robots) deployed to GitHub Pages by `.github/workflows/deploy-site.yml`. The
  site is a separate project with its own build; the app stays build-free.
  Replaces the earlier static `docs/index.html` landing page.
### Changed
- **License is now PolyForm Noncommercial 1.0.0** (was MIT). The project is
  source-available and free for **any noncommercial use** — personal, hobby,
  education, research, non-profits — but **commercial use, including selling it
  or bundling it into a paid product, is not permitted** without a separate
  license. This is not OSI "open source"; docs and badges reflect that.
- **Alert webhook field is readable.** In the ⚙ settings popover the webhook URL
  shared the cramped numeric-input width, so the address was truncated to
  `https://nt…`. It now sits on its own full-width row below a divider, so the
  whole URL is visible while typing.

## [1.33.1] - 2026-07-07
### Changed
- **Neutral example address.** The "＋ machine" input's placeholder now shows a
  generic example address (`100.64.0.1`) instead of a specific machine's IP.

## [1.33.0] - 2026-07-02
### Added
- **Runners grouped by project.** When a machine runs runners for more than one
  repo, the Runner status widget groups them under a per-repo header (repo name +
  runner count + how many are busy) instead of a flat mix, and drops the now-
  redundant per-card repo line inside a group. A machine serving a single repo
  stays flat. The detail modal still resolves (original runner index preserved).

## [1.32.1] - 2026-07-02
### Changed
- **Runner card names are readable again.** The runner name shared one row with
  the status pill and the 🔔 mute bell, so longer names (e.g. `si-mac2-android-ci`)
  truncated. The name now gets its own full-width row; the status pill moved down
  onto the repo line, and the mute toggle moved to the card's top-right corner
  (hover-reveal, always shown when muted).

## [1.32.0] - 2026-07-02
### Added
- **Disk-fill alert.** When the disk-fill ETA drops to ≤3 days, it raises an alert
  (banner / notification / webhook) — e.g. "disk full in ~2d" — so you act before
  it's critical.
- **Active runs link to GitHub Actions.** Each active-run row's repo is now a link
  (↗) to that repo's Actions page.
- **Idle runners show when they last ran.** An idle runner card shows "last job
  Nm ago" next to its uptime, so a runner that stopped picking up work stands out.
### Changed
- **Reliable test suite.** Tests point the AI/CodexBar paths at nonexistent files
  by default, so the TCC-protected snapshot is never touched — `python -m unittest
  discover -s tests` is now consistently green in ~3s (was slow/flaky when run
  interactively). Dev-only.

## [1.31.0] - 2026-07-02
### Fixed
- **Disk usage now matches macOS Storage.** The dashboard reported `total - free`,
  but on APFS `free` excludes purgeable space (caches, local snapshots) that macOS
  counts as available — so a disk macOS shows at ~92% (tens of GB available) read
  ~99%, even tripping false "critical disk" alerts. It now uses the
  purgeable-inclusive available capacity (Foundation's
  `volumeAvailableCapacityForImportantUsageKey`, read via ctypes — the same
  approach as the FDA-binary path — cached by the background sampler), and falls
  back to `total - free` when the API is unavailable.

## [1.30.1] - 2026-07-02
### Fixed
- **Mobile layout overflow.** On narrow screens the pinned-widget area and the
  machine grid used a fixed `minmax(440px, …)` that overflowed the viewport, and
  the header button row (now 7 icons) didn't wrap. Grids use
  `minmax(min(440px,100%),1fr)` so a column never exceeds the screen, the header
  cluster wraps, and popovers (⚙ / 📋) span the width instead of running off-screen.

## [1.30.0] - 2026-07-02
### Added
- **Recent-events log** (📋). A header button opens a popover listing the last
  state transitions the alert pipeline saw — runner offline/online, CI failures,
  dead-man check late/down — each with an icon + relative time, so you can see
  "what happened while I was away." Persisted per browser (last 60), with a clear
  button. Purely client-side, derived from the polled data.
- **Snooze all alerts / maintenance mode** (😴). A header button silences every
  alert (banner, notifications, webhook) for 1 hour; the banner shows a muted
  `🔕 snoozed · Nm · K hidden` instead of the red alert. Events are still logged
  while snoozed, and nothing re-fires when the snooze ends. Click again to resume.

## [1.29.0] - 2026-07-02
### Added
- **Active runs show elapsed time.** Each active-run row now shows how long it has
  been running (`⏱ 35m`) — the longest of its jobs — so a slow or stuck run is
  obvious at a glance.
- **Screen-sharing (VNC) shortcut.** The per-machine SSH chip gains a 🖥 button
  that opens `vnc://<user>@<tailscale-ip>` in macOS Screen Sharing, next to the
  `>_` ssh:// link and the `⧉` copy button — handy for a Mac fleet.

## [1.28.0] - 2026-07-02
### Changed
- **Active runs now show which repo/project they belong to.** Each active-run row
  leads with the repository (e.g. `acme/webapp`) instead of just the
  branch, plus a commit-message + actor subline — so a plain push to `main` is no
  longer ambiguous when several projects are running. Runs are now grouped by repo
  too, so two projects both building `main` stay separate (they could previously
  merge into one row).

## [1.27.1] - 2026-07-02
### Changed
- **Pinned widgets show the machine's name, not "Local".** A widget pinned (★)
  from the machine serving the page was tagged `Local`, which is confusing when
  you open the dashboard from another Mac (e.g. viewing the hub from ekos). It now
  shows the real computer name, matching how peers' pinned widgets are tagged.

## [1.27.0] - 2026-07-02
### Added
- **Mute a runner's offline alert.** A 🔔 toggle on each runner card silences the
  "runner offline" alert for that specific runner (persisted per browser) — for
  runners you stopped on purpose, so a known-down CLI doesn't nag. Muted runners
  show 🔕; other anomalies (stuck job, CI failure) still alert. Click again to
  unmute. Key is `<machine base>|<runner name>` in `sysdash-muted-runners`.

## [1.26.0] - 2026-07-02
### Added
- **Per-machine SSH shortcut.** Each machine header gets a `>_` chip: click it to
  open `ssh://<user>@<tailscale-ip>` in the OS's `ssh://` handler (set iTerm2 as
  that handler to use it, otherwise Terminal opens), plus a `⧉` button that copies
  the `ssh <user>@<tailscale-ip>` command. The login user is read locally
  (`getpass.getuser()` → `stats.user`); the session opens from whichever machine is
  viewing the dashboard and connects over the tailnet (plain sshd — needs Remote
  Login enabled on the target). No backend call — a pure client-side link/clipboard.

## [1.25.0] - 2026-06-30
### Added
- **Process app rollup.** The top-processes widget gains an **Apps** view that
  groups a multi-process app's children into one row — `Google Chrome ×41 ·
  2.2 GB` — so you see which *app* is eating RAM, not eight scattered helper rows.
  `stats.top_groups`; grouping collapses `AppName Helper (…)` → `AppName`.
- **Baseline anomaly cue.** Each gauge shows a subtle `↑ unusual` / `↓ low` hint
  when the current CPU/mem/disk is more than 2σ from its own last-24h average
  (z-score from the history DB) — catches "abnormal for *now*" that fixed
  thresholds miss. No extra alerts/banners; `stats.baseline`.
### Fixed
- Demo mode (`?demo`) top-processes widget was empty: the sample data used an old
  `top:{mem,cpu}` object instead of the `top[]` / `top_cpu[]` arrays the UI reads.

## [1.24.1] - 2026-06-30
### Fixed
- **Interactive runs no longer hang on the CodexBar snapshot.** The richer
  `widget-snapshot.json` lives in a TCC-protected Group Container. Under launchd
  the gate denies instantly, but in an interactive terminal (`python server.py`
  for local preview) it can pop a consent dialog and block the read forever,
  hanging `/api/stats` and `--status`. The snapshot read now runs in a daemon
  thread with a short timeout; on timeout it's skipped and the history-based
  fallback is kept. launchd behavior is unchanged.

## [1.24.0] - 2026-06-30
### Added
- **Per-interface network breakdown** (#38). The system card splits network into
  per-NIC rates (en0 vs Tailscale `utun…`) from `net_io_counters(pernic=True)`,
  filtering loopback/trivial interfaces. `stats.net_ifaces`.
- **Daily bandwidth total** (#38). A new `net_daily` SQLite table accumulates each
  minute's bytes; the system card shows today's ↓/↑ totals (`stats.net_today`,
  30-day retention). Closes #38 — the competitor-scan roadmap (#29–#41) is done.

## [1.23.0] - 2026-06-30
### Added
- **Runner queue depth / wait-time** (#41). `get_queue_stats()` reads the jobs
  table and flags contention: on serial self-hosted runners a job starting within
  45s of the previous one's end was queued waiting. The runner modal shows a
  "Queue pressure" bar (% of jobs queued + est. wait) — a fleet-sizing capacity
  signal the busy/idle view can't give. `stats.queue` keyed by runner dir.
### Changed
- **Off-browser alerts** (#40, complete). Server-fired dead-man check alerts now
  also post a native macOS notification (`osascript`) when a check goes
  late/down, deduped until it recovers — delivery no longer needs an open browser
  tab. (The webhook channel shipped in 1.22.0.)

## [1.22.0] - 2026-06-30
### Added
- **Dead-man / cron health checks** (#39). A cron job hits
  `GET /api/ping?job=<name>&period=<sec>&grace=<sec>` on success; the server
  remembers the last ping in SQLite and derives a state (up → late → down) once
  the job goes silent past `period + grace`. A "Scheduled checks" strip shows
  every check across the fleet, and late/down checks raise the existing alert
  banner + notifications. Fully self-contained — no external service.
- **Off-browser alerts** (#40, webhook). The ⚙ settings popover takes an alert
  webhook URL (ntfy.sh / Slack / Discord); each *new* alert is POSTed there so
  notifications reach you when the dashboard tab isn't open. Alerts are seeded on
  first load so a refresh doesn't replay old ones. (Native `osascript`
  notifications for server-fired alerts remain open in #40.)

## [1.21.0] - 2026-06-29
### Added
- **Thermal pressure badge** (#38). `pmset -g therm` (background thread, 30s)
  surfaces SoC throttling the CPU% gauge hides — a 🌡 chip appears on a machine's
  header when its CPU speed limit drops below 100%. `stats.thermal {state,
  cpu_limit}`.
- **Disk I/O throughput** (#38). `psutil.disk_io_counters()` read/write rates in
  the system card with a sparkline (`stats.io`, `hist.disk_read`/`disk_write`).
- **Load-average sparkline** (#38). The system card's load row gains a trend
  sparkline from the new `hist.load`.

  (Per-core CPU breakdown was already present; per-interface net split and daily
  bandwidth total from #38 remain open.)

## [1.20.0] - 2026-06-29
### Added
- **Flaky CI job detection** (#30). The runner modal lists jobs that both pass
  and fail over the last 14 days (10–90% fail rate, ≥3 runs) with their fail
  rate — a job that always fails is broken, not flaky, and is excluded. Served
  as `stats.flaky` keyed by runner dir.
- **Active runs view** (#31). A fleet panel groups currently-busy runners across
  all machines by their run identity (PR / branch + workflow), so one run split
  across several runners/Macs shows as a single entry with per-runner job chips.
- **Self-update badge** (#32). A header badge shows how many commits this
  checkout is behind `origin/main`, refreshed hourly by a background thread
  (`stats.update_behind`); the hot stats path never shells out to git.
- **TV / wall-display mode** (#34). A 📺 toggle (or `?tv`) hides the chrome,
  scales the layout up, and widens the machine grid for an always-on display.
  Persists in localStorage.

## [1.19.0] - 2026-06-29
### Added
- **Disk-fill ETA** (#29). The disk gauge shows time-to-full (`⏳~6d`) when the
  disk is trending up — from the least-squares slope of disk% over the last 24h
  of history. Hidden when flat/shrinking or more than 30 days out.
- **Configurable alert thresholds** (#33). A ⚙ settings popover sets Critical %,
  Warning %, and stuck-job minutes; persisted in localStorage and applied live
  (defaults 95 / 75 / 30 unchanged when untouched).

## [1.18.0] - 2026-06-29
### Added
- **CI failure alerts.** A runner job that just finished as `Failed` now raises a
  banner + browser notification (via the existing alert pipeline), deduped per
  job run so old failures and page reloads don't spam (the first poll only seeds
  the seen-set; `runner_history` items now carry a unique `id`).

### Fixed
- AI widget reset times: a space after the `↻` (`↻ 46m`) so it's readable.

## [1.17.0] - 2026-06-29
### Changed
- **Header reworked for the multi-machine reality.** Dropped the app emoji icon
  and the single-machine "Tailscale <ip> · N cores" subtitle (it only described
  one PC). The header now shows the connected-**device count** with a status dot
  per device (green = online), scaling as machines are added. Each machine's
  Tailscale address + core count moved under its own name in the machine card.

## [1.16.0] - 2026-06-29
### Added
- **AI Copilot reset times.** Each provider's Session and Weekly rows now show
  when the quota resets (`↻ <time left>`, e.g. `Session · ↻46m`, `Weekly · ↻5d 18h`),
  with the absolute reset time on hover. Parsed from CodexBar's `resetsAt`
  timestamps in both the history fallback and the snapshot.

## [1.15.2] - 2026-06-29
### Fixed
- The Full Disk Access hint still pointed at the wrong binary. Framework Python's
  `bin/python3.9` is a stub that `exec`s `Resources/Python.app/Contents/MacOS/Python`;
  TCC matches that real binary, but `realpath(sys.executable)` only resolves
  symlinks and stops at the stub — so granting FDA to the hinted path had no
  effect. The hint now reports the actual running executable via
  `_NSGetExecutablePath` (ctypes), which is what FDA must be granted to.

## [1.15.1] - 2026-06-29
### Fixed
- The Full Disk Access hint reported `sys.executable`, which is usually a symlink
  (`venv/bin/python`). macOS's FDA file picker won't let you select an alias, so
  the path was unusable. It now reports `os.path.realpath(sys.executable)` — the
  real Mach-O binary, which is selectable.

## [1.15.0] - 2026-06-29
### Added
- **Full Disk Access hint in the AI widget.** When CodexBar's richer
  `widget-snapshot.json` exists but the `launchd` agent can't read it (macOS TCC
  blocks Group Containers), the AI widget now shows the **exact binary path** to
  grant Full Disk Access to. A background launchd agent appears as a generic
  "Python" entry with no app name, so this removes the guesswork. Claude + Codex
  keep coming from the always-readable history fallback with no FDA needed; this
  only unlocks providers that live solely in the snapshot (e.g. Antigravity).

## [1.14.0] - 2026-06-29
### Added
- **Runner CI health heatmap (rebuilt).** A 30-day GitHub-style grid in the
  runner detail modal, coloured by **outcome** — green (all ok), amber (some
  fails), red (all fails), muted (no jobs) — with a legend. The earlier card
  heatmap was removed for being confusing: it mixed failure *and* job volume in
  one colour scale and sat next to the recent-job dots. This version lives in the
  modal, colours by health only, and uses UTC dates to match stored timestamps.

### Fixed
- **Escaping:** three remote-controlled strings were rendered into the DOM
  without `esc()` — top-process names, the machine/host name, and the pinned
  widget's machine label. Process names are notable because runners execute
  untrusted CI code, so an injected name could run in a viewer's browser.
- **Per-machine widget reorder** targeted a non-existent `.column` element, so a
  drag-reorder on a peer machine was saved under the local key; now uses
  `.machine` (matching how the order key is written/read).
- **`sparkSVGNet`** no longer throws when a payload has `net_down` history but no
  `net_up` (now guards both arrays).
- **Heatmap edge case:** a day with only non-pass/fail outcomes showed as empty
  while the tooltip reported jobs; now rendered as a neutral cell.

## [1.13.3] - 2026-06-29
### Fixed
- AI Copilot widget was empty under the `launchd` agent. `_get_ai_stats()` read
  the history fallback first, then attempted the richer Group-Containers
  `widget-snapshot.json`; under `launchd` that `open()` raises a TCC
  `PermissionError` that fell through to the outer `except`, which returned the
  (empty) cache and **discarded the fallback data just collected**. The
  snapshot read is now wrapped in its own `try/except`, so a blocked/missing
  primary keeps the history fallback (Claude + Codex). Antigravity still needs
  the primary (grant the agent Full Disk Access to surface it under launchd).

## [1.13.2] - 2026-06-27
### Fixed
- Swap usage bar now turns **red** at ≥90%. The colour thresholds were ordered
  `≥70 → amber` before `≥90 → red`, so the amber branch caught every high value
  first and the red branch was unreachable (a 95% swap showed amber).

## [1.13.1] - 2026-06-27
### Fixed
- Fixed an issue where the background `launchd` service silently failed to load dynamic AI Copilot stats due to macOS Sandbox (TCC) restrictions on `Group Containers`, by re-introducing the old `history/` read method as a resilient fallback.
- Fixed a logic bug where pinning a widget on the local machine (`host.base=""`) would successfully mark it as pinned but fail to move it to the global pinned area.

## [1.13.0] - 2026-06-26
### Added
- **Global Widget Pinning:** Added a star (★) button to pin any widget (AI Copilot, Gauges, Runners, etc.) to a new full-width global header area at the top of the dashboard.
- **Dynamic AI Copilot Providers:** The AI widget now dynamically reads all available providers (including Antigravity) from `widget-snapshot.json` and automatically scales the layout.

### Changed
- **Independent Layout States:** Widget collapse and pinning states are now tracked independently per machine (`hostBase`) rather than globally, fixing mirrored layout issues across multiple devices.
- **Runner UI Clean up:** Removed the 30-day GitHub-style job heatmap from runner cards for a cleaner, less cluttered interface.

## [1.12.0] - 2026-06-26
### Added
- **Widget Drag & Drop:** Fully customizable and persistent layout. Reorder Gauges, Runners, System, and Top Processes freely by dragging their headers.
- **AI Copilot Usage Widget:** Automatically integrates with CodexBar to display active Claude and GitHub Copilot session & weekly usage directly on the dashboard.
- **Uptime SLA Tracking:** Calculates and displays a 24-hour and 7-day Uptime SLA percentage (`✨ 99.9%`) on the machine header using the existing zero-dependency SQLite history database.

# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).
## [1.11.0] - 2026-06-26

### Added
- **Runner Heatmap:** Added a GitHub-style 30-day contribution heatmap for each runner directly on the dashboard card.
- **Runner Timeline:** Added a Gantt chart timeline view inside the runner detail modal, showing a graphical representation of the last 50 jobs executed.
- **Persistent Job History:** `server.py` now includes a background thread that continually parses `Worker_*.log` files and stores historical job runs in a new `jobs` SQLite table.
- New endpoints: `/api/jobs` and `/api/peer_jobs` for cross-node timeline fetching.


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
