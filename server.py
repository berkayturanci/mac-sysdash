#!/usr/bin/env python3
"""Tiny system + GitHub Actions runner dashboard.

Serves a single polished HTML page plus a /api/stats JSON endpoint.
Designed to run under the glances virtualenv python (has psutil) and be
reached over Tailscale. No external deps beyond psutil + stdlib.
"""
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("SYSDASH_PORT", "8765"))

# Self-hosted runners installed on this Mac.
HOME = os.path.expanduser("~")

# Where to look for self-hosted runner installs. Each runner dir contains a
# ".runner" JSON config (agentName, gitHubUrl). New runners installed under any
# of these roots are picked up automatically — no code change needed.
#
# IMPORTANT: only list directories that are NOT TCC-protected. As a launchd
# background agent (no Full Disk Access), touching ~/Documents, ~/Desktop,
# ~/Downloads, iCloud/CloudStorage, etc. can BLOCK forever on the TCC gate.
# All runners on this Mac live under ~/GitHub, which is not protected. Runners
# started from anywhere else are still discovered via running processes below.
RUNNER_ROOTS = [
    os.path.join(HOME, "GitHub"),
    os.path.join(HOME, "actions-runners"),
]


def tailscale_ip():
    try:
        out = subprocess.run(["/usr/local/bin/tailscale", "ip", "-4"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip().splitlines()[0]
    except Exception:
        return ""


TAILSCALE_IP = tailscale_ip()


def computer_name():
    try:
        out = subprocess.run(["/usr/sbin/scutil", "--get", "ComputerName"],
                             capture_output=True, text=True, timeout=3)
        name = out.stdout.strip()
        if name:
            return name
    except Exception:
        pass
    return socket.gethostname()


HOSTNAME = computer_name()

# Background CPU sampler so HTTP requests never block on cpu_percent().
_CPU = {"pct": 0.0, "cores": [], "count": psutil.cpu_count() or 0}


def _cpu_sampler():
    while True:
        cores = psutil.cpu_percent(interval=1.0, percpu=True)
        _CPU["cores"] = [round(c, 1) for c in cores]
        _CPU["pct"] = round(sum(cores) / len(cores), 1) if cores else 0.0
        _CPU["count"] = len(cores)


def _read_runner_cfg(runner_dir):
    """Return (name, repo) from a runner's .runner config, or None if not one."""
    cfg = os.path.join(runner_dir, ".runner")
    if not os.path.isfile(cfg):
        return None
    name, repo = os.path.basename(runner_dir), ""
    try:
        with open(cfg, encoding="utf-8-sig") as f:  # .runner has a UTF-8 BOM
            data = json.load(f)
        name = data.get("agentName") or name
        url = (data.get("gitHubUrl") or "").rstrip("/")
        repo = url.split("github.com/")[-1] if "github.com/" in url else url
    except Exception:
        pass
    return name, repo


_DISC = {"ts": 0.0, "runners": []}   # cache discovered runner *definitions*


def discover_runners(ttl=30):
    """Find runner installs from disk + any running runner processes.

    Cached for `ttl` seconds. A newly installed runner under RUNNER_ROOTS (or
    one started anywhere on disk) shows up automatically within the TTL.
    """
    now = time.time()
    if now - _DISC["ts"] < ttl and _DISC["runners"]:
        return _DISC["runners"]

    found = {}  # dir -> {name, repo}

    # 1) filesystem: scan immediate subdirs of each root for a .runner file,
    #    and the roots themselves (e.g. ~/actions-runner).
    seen_dirs = set()
    for root in RUNNER_ROOTS:
        candidates = [root]
        try:
            candidates += [e.path for e in os.scandir(root) if e.is_dir()]
        except Exception:
            pass
        for d in candidates:
            rd = os.path.realpath(d)
            if rd in seen_dirs:
                continue
            seen_dirs.add(rd)
            cfg = _read_runner_cfg(rd)
            if cfg:
                found[rd] = {"name": cfg[0], "repo": cfg[1]}

    # 2) running processes: catch runners installed outside the known roots.
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except Exception:
            continue
        if "Runner.Listener" not in cmd and "Runner.Worker" not in cmd:
            continue
        # cmdline looks like .../<runner_dir>/bin/Runner.Listener ...
        idx = cmd.find("/bin/Runner.")
        if idx == -1:
            continue
        rd = os.path.realpath(cmd[:idx].split()[-1])
        if rd not in found:
            cfg = _read_runner_cfg(rd)
            found[rd] = {"name": cfg[0] if cfg else os.path.basename(rd),
                         "repo": cfg[1] if cfg else ""}

    runners = [{"id": d, "dir": d, "name": v["name"], "repo": v["repo"]}
               for d, v in sorted(found.items(), key=lambda kv: kv[1]["name"].lower())]
    _DISC.update(ts=now, runners=runners)
    return runners


def runner_status():
    """Classify each discovered runner as busy / idle / offline."""
    runners = discover_runners()
    listener, worker = {}, {}   # dir -> create_time
    for p in psutil.process_iter(["cmdline", "create_time"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except Exception:
            continue
        if "Runner.Listener" not in cmd and "Runner.Worker" not in cmd:
            continue
        for r in runners:
            if r["dir"] in cmd:
                tgt = worker if "Runner.Worker" in cmd else listener
                tgt[r["dir"]] = p.info["create_time"]
    result, now = [], time.time()
    for r in runners:
        d = r["dir"]
        if d in worker:
            status, since = "busy", worker[d]
        elif d in listener:
            status, since = "idle", listener[d]
        else:
            status, since = "offline", None
        url = (f"https://github.com/{r['repo']}/settings/actions/runners"
               if r["repo"] else "")
        result.append({
            "id": r["id"], "name": r["name"], "repo": r["repo"],
            "status": status,
            "uptime": int(now - since) if since else None,
            "url": url, "dir": d,
        })
    return result


def top_processes(n=8):
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            rss = p.info["memory_info"].rss
            procs.append({"name": p.info["name"] or "?", "rss": rss})
        except Exception:
            continue
    procs.sort(key=lambda x: x["rss"], reverse=True)
    return procs[:n]


def stats():
    cores = _CPU["cores"]
    cpu = _CPU["pct"]
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    # On macOS, "/" is the read-only system snapshot (looks ~empty). The real
    # usage lives on the APFS data volume.
    disk_path = "/System/Volumes/Data" if os.path.isdir("/System/Volumes/Data") else "/"
    du = psutil.disk_usage(disk_path)
    # On APFS the data volume's own `used` excludes system/VM/other volumes, so
    # it disagrees with Finder's Storage figure. Treat everything that is not
    # free in the shared container as used (total - free), which matches what
    # macOS Storage shows and keeps the % consistent with the GB text.
    disk_used = du.total - du.free
    disk_pct = round(disk_used / du.total * 100, 1) if du.total else 0.0
    try:
        load = psutil.getloadavg()
    except Exception:
        load = (0, 0, 0)
    return {
        "host": HOSTNAME,
        "tailscale_ip": TAILSCALE_IP,
        "ts": time.time(),
        "uptime": int(time.time() - psutil.boot_time()),
        "cpu": {"pct": cpu, "cores": cores,
                "count": _CPU["count"], "load": [round(x, 2) for x in load]},
        "mem": {"pct": vm.percent, "used": vm.used, "total": vm.total},
        "swap": {"pct": sw.percent, "used": sw.used, "total": sw.total},
        "disk": {"pct": disk_pct, "used": disk_used, "total": du.total},
        "runners": runner_status(),
        "top": top_processes(),
    }


# Cache the computed stats so concurrent pollers share one computation instead
# of each spawning its own psutil.process_iter sweep (which thrashes threads).
_STATS = {"ts": 0.0, "data": None}
_STATS_LOCK = threading.Lock()


def cached_stats(ttl=0.8):
    now = time.time()
    with _STATS_LOCK:
        if _STATS["data"] is None or now - _STATS["ts"] > ttl:
            _STATS["data"] = stats()
            _STATS["ts"] = now
        return _STATS["data"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/stats"):
            try:
                body = json.dumps(cached_stats()).encode()
                self._send(200, body, "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode(),
                           "application/json")
            return
        path = "/index.html" if self.path in ("/", "") else self.path
        fp = os.path.normpath(os.path.join(HERE, path.lstrip("/")))
        if fp.startswith(HERE) and os.path.isfile(fp):
            with open(fp, "rb") as f:
                body = f.read()
            ctype = "text/html; charset=utf-8" if fp.endswith(".html") else "text/plain"
            self._send(200, body, ctype)
        else:
            self._send(404, b"not found", "text/plain")


if __name__ == "__main__":
    threading.Thread(target=_cpu_sampler, daemon=True).start()
    ThreadingHTTPServer.daemon_threads = True
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"sysdash on http://0.0.0.0:{PORT}  (tailscale {TAILSCALE_IP})")
    srv.serve_forever()
