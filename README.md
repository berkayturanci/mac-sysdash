# mac-sysdash

![platform](https://img.shields.io/badge/platform-macOS-black)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![version](https://img.shields.io/badge/version-1.3.1-blue)
![tests](https://github.com/berkayturanci/mac-sysdash/actions/workflows/test.yml/badge.svg)

A tiny, dependency-light **system + GitHub Actions runner dashboard** for macOS,
reachable over your LAN or [Tailscale](https://tailscale.com/) from any device.

<p align="center">
  <img src="docs/hero.png" width="880"
       alt="mac-sysdash dashboard: CPU/memory/disk ring gauges, self-hosted runner status, and system detail">
</p>

It is a single Python file (stdlib HTTP server) plus one HTML file. The only
third-party dependency is [`psutil`](https://github.com/giampaolo/psutil) — and
the installer sets that up for you in an isolated virtualenv.

## Features

- **CPU / Memory / Disk** ring gauges (blue → amber → red), refreshing every second.
  - On macOS, **disk** usage is read from the APFS data volume and reported as
    `total − free`, and **memory** as `total − available`, so the percentages
    match Finder's Storage and Activity Monitor instead of under-counting.
- **High-usage alerts** at ≥95%: a red badge on the gauge, a top banner, and a
  `⚠️` prefix in the browser tab title so you notice even from another tab.
- **GitHub Actions self-hosted runners**, auto-discovered, with a live status pill
  (`busy` / `idle` / `offline`):
  - For a **busy** runner, the card shows what it is working on — **branch**,
    **workflow**, **PR / issue**, **commit**, and the triggering **actor** —
    read locally from the runner's event payload (no GitHub token needed).
  - A row of **recent-job dots** (green = succeeded, red = failed) per runner.
  - **Click a runner for a detail modal** — the current job plus the last 5 runs
    (workflow · branch · result · duration), each linking to that workflow's runs
    on GitHub, with shortcuts to the Actions page and runner settings.
- **Multiple machines side by side**, filling the width and wrapping down. Peers are
  **auto-discovered** on your tailnet (any reachable mac-sysdash), or added manually.
  **Drag a panel by its header to reorder.**
- **Collapsible sections** — fold Runner status / System / Top processes to keep just
  the CPU / memory / disk gauges in view.
- **System detail** — per-core CPU bars, load average, RAM/swap/disk, network
  throughput, battery, uptime, and the top memory-consuming processes.
- **Trends** — a 60-second sparkline under each gauge; **click a gauge** for a larger
  ~5-minute CPU/memory chart.
- **Notifications** — desktop/phone alerts when a metric goes critical (needs HTTPS).
- **Per-machine local time** (with timezone) — handy across timezones.
- **Installable (PWA)** — "Add to Home Screen" on iOS/Android for an app-like,
  full-screen view from your phone.
- **Light / dark / auto theme** following the system appearance, with a toggle.
- **English / Turkish UI** — defaults to the system language, with an
  auto / EN / TR selector.
- **Light on resources** — ~20 MB RAM, ≈0 % CPU. Runs at login and self-restarts
  via a per-user `launchd` agent.

## Requirements

- macOS (tested on Apple Silicon)
- `python3` (the Xcode Command Line Tools provide one: `xcode-select --install`)

`psutil` is installed automatically into a virtualenv by `install.sh`; nothing
else is required.

## Install

```sh
git clone https://github.com/berkayturanci/mac-sysdash.git
cd mac-sysdash
./install.sh
```

The installer runs the app **in place from this repo clone** (no copy), ensures
`psutil` (using an existing interpreter that has it, otherwise a fresh venv under
`venv/`), generates a per-user `launchd` agent, and starts it. The dashboard then
runs at login, restarts on crash, and listens on all interfaces:

```
http://localhost:8765
http://<your-tailscale-ip>:8765   # from another device on your tailnet
```

Change the port with `SYSDASH_PORT=8770 ./install.sh`.

## Updating

```sh
git pull && ./install.sh
```

The page (`index.html`) is read live on each request, so a `git pull` updates the
UI immediately; re-running `install.sh` restarts the agent to pick up `server.py`
changes.

## Uninstall

```sh
./uninstall.sh
```

## Multiple machines

Run mac-sysdash on each machine, then add the others as peers from the page —
click **＋ machine** in the host bar and enter an address (e.g. `100.121.169.10`;
the `:8765` port is added automatically). Each machine is polled directly from
your browser and rendered as its own panel; an unnamed peer shows its own
hostname once reachable, and unreachable peers show an **offline** card.

This works because the server sends `Access-Control-Allow-Origin: *`, so the
browser may read `/api/stats` from every peer. Peers are stored in your
browser's `localStorage`, so they are per-viewer.

## Runner auto-discovery

Runners are discovered two ways, with no code changes when you add one:

1. **Filesystem** — directories under the roots in `RUNNER_ROOTS` (`server.py`)
   that contain a runner's `.runner` config file. Default: `~/GitHub`.
   > Keep these roots out of TCC-protected folders (`~/Documents`, `~/Desktop`,
   > `~/Downloads`, iCloud/CloudStorage). A `launchd` background agent without
   > Full Disk Access can block indefinitely when touching them.
2. **Running processes** — any live `Runner.Listener` / `Runner.Worker` process,
   wherever it is installed.

Status: a `Runner.Worker` means **busy**, a `Runner.Listener` alone means
**idle**, neither means **offline**.

The displayed runner name comes from each runner's own `.runner` config
(`agentName`), so renaming a runner is reflected here automatically.

## Runner naming (recommended)

The dashboard reads each runner's registered name, so a consistent scheme makes
a multi-machine fleet readable at a glance:

- **Name = `<machine>-<role>`** — a stable per-machine token plus its purpose
  (e.g. `mbp-ingreview`, `ekos-web-ci`). Names are unique per repo and exist for
  humans to tell machines apart, so avoid generic tokens like `mac` when you run
  more than one Mac.
- **Labels do the routing, not the name.** Workflows target
  `runs-on: [self-hosted, macOS, ARM64, <custom>]`; the default labels plus any
  capability labels (`android`, `web`, …) decide which runner picks up a job, so
  you can rename a runner without breaking any workflow.
- Lowercase, hyphen-separated; keep the same machine token across every repo a
  machine serves.

To rename an existing runner, re-register it (no workflow changes needed):

```sh
cd <runner-dir>
TOKEN=$(gh api -X POST repos/<owner>/<repo>/actions/runners/registration-token --jq .token)
./svc.sh stop && ./svc.sh uninstall
./config.sh remove --token "$(gh api -X POST repos/<owner>/<repo>/actions/runners/remove-token --jq .token)"
./config.sh --url https://github.com/<owner>/<repo> --token "$TOKEN" --name <new-name> --unattended --replace
./svc.sh install && ./svc.sh start
```

## HTTPS & notifications (optional)

The bell in the header can push a desktop/phone notification when a machine goes
critical — but browsers only allow notifications in a **secure context**. Expose
mac-sysdash over HTTPS on your tailnet with [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve):

```sh
./serve.sh
```

This prints a clean `https://<host>.<tailnet>.ts.net` URL (no port). Open it,
click the bell to grant permission, and you'll get alerts even from your phone.
Stop sharing with `tailscale serve reset`. (Requires HTTPS enabled for your
tailnet in the Tailscale admin console.)

## Tests

A `unittest` suite (no third-party deps beyond `psutil`) covers config/event/log
parsing, the disk/memory invariants, tailnet peer discovery, battery, and the
HTTP routes. Run it with any Python that has `psutil`:

```sh
python3 -m unittest discover -s tests -v
# or, if the installer created one:
./venv/bin/python -m unittest discover -s tests -v
```

CI runs the same suite on every push/PR (`.github/workflows/test.yml`).

## Configuration

At the top of `server.py`:

- `PORT` / `SYSDASH_PORT` — listening port (default `8765`)
- `RUNNER_ROOTS` — where to scan for runner installs
- `VERSION` — shown in the page footer

## How it works

- A background thread samples CPU once per second so HTTP requests never block.
- `/api/stats` returns a JSON snapshot; the page polls it every second.
- The snapshot is cached for ~0.8 s behind a lock, so many concurrent viewers
  share one computation instead of each spawning a process scan.
- A busy runner's job context comes from
  `<runner>/_work/_temp/_github_workflow/event.json` — the webhook payload the
  runner already writes locally.

## Troubleshooting

- **A peer shows "offline" / unreachable.** Confirm sysdash is running there
  (`curl -s localhost:8765/api/stats` returns JSON) and that the address
  includes a reachable host. If it answers locally but not over Tailscale, the
  macOS firewall is likely dropping incoming connections — allow the interpreter
  in System Settings → Network → Firewall, or turn the firewall off.
- **Port already in use.** Reinstall on another port: `SYSDASH_PORT=8770 ./install.sh`.
- **Logs.** `~/.local/log/sysdash.log`.

## License

MIT — see [LICENSE](LICENSE).
