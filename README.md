# mac-sysdash

![platform](https://img.shields.io/badge/platform-macOS-black)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![version](https://img.shields.io/badge/version-1.0.0-blue)

A tiny, dependency-light **system + GitHub Actions runner dashboard** for macOS,
reachable over your LAN or [Tailscale](https://tailscale.com/) from any device.

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
  - Click a runner to open its PR (when building one) or its GitHub runner
    settings. Hover to reveal any truncated detail.
- **Multiple machines side by side** — add peer machines (e.g. via their
  Tailscale IP) and watch them all in one view.
- **System detail** — per-core CPU bars, load average, RAM/swap/disk, uptime,
  and the top memory-consuming processes.
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

The installer copies the app to `~/.local/share/sysdash`, ensures `psutil` (using
an existing interpreter that has it, otherwise a fresh venv), generates a
per-user `launchd` agent, and starts it. The dashboard then runs at login,
restarts on crash, and listens on all interfaces:

```
http://localhost:8765
http://<your-tailscale-ip>:8765   # from another device on your tailnet
```

Change the port with `SYSDASH_PORT=8770 ./install.sh`.

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
