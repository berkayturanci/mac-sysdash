# mac-sysdash

A tiny, dependency-light **system + GitHub Actions runner dashboard** for macOS,
reachable over your LAN or [Tailscale](https://tailscale.com/) from any device.

It serves a single polished HTML page that shows, refreshing every second:

- **CPU / Memory / Disk** as colored ring gauges (blue → amber → red)
- **High-usage alerts** at ≥90%: a red badge on the gauge, a top banner, and a
  `⚠️` prefix in the browser tab title so you notice even from another tab
- **GitHub Actions self-hosted runners**, auto-discovered, with a live status pill
  (`busy` / `idle` / `offline`). Click a runner to open its GitHub runner settings
- **System detail** — per-core CPU bars, load average, RAM/swap/disk, uptime, and
  the top memory-consuming processes
- **Light / dark / auto theme** that follows the system appearance, with a toggle

It is a single Python file (stdlib HTTP server) plus one HTML file. The only
third-party dependency is [`psutil`](https://github.com/giampaolo/psutil).

## Screenshots

Dark and light themes, runner cards, and ring gauges. (Add your own.)

## Requirements

- macOS (tested on Apple Silicon)
- Python 3.9+ with `psutil` available
  - If you have [Glances](https://nicolargo.github.io/glances/) installed via
    Homebrew, its bundled Python already has `psutil` and the installer will use it.
  - Otherwise: `pip3 install psutil`

## Install

```sh
git clone https://github.com/berkayturanci/mac-sysdash.git
cd mac-sysdash
./install.sh
```

The installer copies the app to `~/.local/share/sysdash`, generates a per-user
`launchd` agent, and starts it. The dashboard then runs at **boot/login**,
restarts itself if it crashes, and listens on all interfaces:

```
http://localhost:8765
http://<your-tailscale-ip>:8765   # from another device on your tailnet
```

Change the port with `SYSDASH_PORT` (see `install.sh`).

## Uninstall

```sh
./uninstall.sh
```

## Runner auto-discovery

Runners are discovered two ways, with no code changes when you add one:

1. **Filesystem** — directories under the roots in `RUNNER_ROOTS` (`server.py`)
   that contain a runner's `.runner` config file. By default this is `~/GitHub`.
   > Keep these roots out of TCC-protected folders (`~/Documents`, `~/Desktop`,
   > `~/Downloads`, iCloud/CloudStorage). A `launchd` background agent without
   > Full Disk Access can block indefinitely when touching them.
2. **Running processes** — any live `Runner.Listener` / `Runner.Worker` process,
   wherever it is installed.

Status is derived from those processes: a `Runner.Worker` means **busy**, a
`Runner.Listener` alone means **idle**, and neither means **offline**.

## Configuration

Everything is at the top of `server.py`:

- `PORT` / `SYSDASH_PORT` — listening port (default `8765`)
- `RUNNER_ROOTS` — where to scan for runner installs

## How it works

- A background thread samples CPU once per second so HTTP requests never block.
- `/api/stats` returns a JSON snapshot; the page polls it every second.
- The snapshot is cached for ~0.8s behind a lock, so many concurrent viewers
  share one computation instead of each spawning a process scan.

## License

MIT — see [LICENSE](LICENSE).
