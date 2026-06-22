#!/usr/bin/env python3
"""Tiny system + GitHub Actions runner dashboard.

Serves a single polished HTML page plus a /api/stats JSON endpoint.
Designed to run under the glances virtualenv python (has psutil) and be
reached over Tailscale. No external deps beyond psutil + stdlib.
"""
import glob
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("SYSDASH_PORT", "8765"))
VERSION = "1.4.0"

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

# Background sampler so HTTP requests never block. It also derives network
# throughput (per-second deltas) and keeps a short CPU/memory history for the
# UI sparklines.
_CPU = {"pct": 0.0, "cores": [], "count": psutil.cpu_count() or 0}
_NET = {"up": 0.0, "down": 0.0}
_HIST = {"cpu": [], "mem": []}
_HIST_LEN = 300  # ~5 min of 1s samples (sparkline uses the last 60; chart uses all)
_prev_net = None


def _cpu_sampler():
    global _prev_net
    while True:
        cores = psutil.cpu_percent(interval=1.0, percpu=True)
        _CPU["cores"] = [round(c, 1) for c in cores]
        _CPU["pct"] = round(sum(cores) / len(cores), 1) if cores else 0.0
        _CPU["count"] = len(cores)
        try:
            n = psutil.net_io_counters()
            if _prev_net is not None:
                _NET["up"] = max(0, n.bytes_sent - _prev_net.bytes_sent)
                _NET["down"] = max(0, n.bytes_recv - _prev_net.bytes_recv)
            _prev_net = n
        except Exception:
            pass
        try:
            vm = psutil.virtual_memory()
            mp = round((vm.total - vm.available) / vm.total * 100, 1) if vm.total else 0.0
            _HIST["cpu"].append(_CPU["pct"])
            _HIST["mem"].append(mp)
            for k in _HIST:
                if len(_HIST[k]) > _HIST_LEN:
                    del _HIST[k][:-_HIST_LEN]
        except Exception:
            pass


def battery_info():
    try:
        b = psutil.sensors_battery()
    except Exception:
        b = None
    if b is None:
        return None
    secs = b.secsleft
    if secs is None or secs < 0:
        secs = None
    return {"pct": round(b.percent), "plugged": bool(b.power_plugged), "secsleft": secs}


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


_PEERS = {"ts": 0.0, "data": []}


def tailnet_peers(ttl=30):
    """Online Tailscale peers (ipv4 + short name), cached. The browser probes
    each for a sysdash on :8765 and auto-adds the ones that answer."""
    now = time.time()
    if now - _PEERS["ts"] < ttl and _PEERS["data"]:
        return _PEERS["data"]
    peers = []
    try:
        out = subprocess.run(["/usr/local/bin/tailscale", "status", "--json"],
                             capture_output=True, text=True, timeout=4)
        data = json.loads(out.stdout)
        for p in (data.get("Peer") or {}).values():
            if not p.get("Online"):
                continue
            ip = next((a for a in (p.get("TailscaleIPs") or []) if ":" not in a), None)
            if ip:
                dns = (p.get("DNSName") or "").rstrip(".")
                nm = (p.get("HostName") or dns or ip).split(".")[0]
                peers.append({"ip": ip, "name": nm, "dns": dns})
    except Exception:
        pass
    _PEERS.update(ts=now, data=peers)
    return peers


# --- server-side peer aggregation ---------------------------------------
# The browser only talks to THIS origin; this server fetches each peer's stats
# over the tailnet (server-to-server, no mixed-content, no per-peer HTTPS), so
# a phone that can reach this Mac sees every machine without each peer needing
# `tailscale serve`. Peers may run sysdash on a non-default port (e.g. 8770).
_PEER_PORTS = (8765, 8770)


def _fetch_stats(url, timeout=2.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        if isinstance(d, dict) and "cpu" in d and "version" in d:
            return d
    except Exception:
        pass
    return None


def _peer_urls(p):
    """Candidate stats URLs for a peer, HTTPS-serve first (only path that some
    nodes accept), then direct app ports for LAN peers without serve."""
    urls = []
    if p.get("dns"):
        urls.append("https://%s/api/stats" % p["dns"])
    for port in _PEER_PORTS:
        urls.append("http://%s:%d/api/stats" % (p["ip"], port))
    return urls


_SPEERS = {"ts": 0.0, "data": []}      # reachable sysdash peers: [{ip,name}]
_PEER_CACHE = {}                       # ip -> (ts, stats, working_url)


def _refresh_sysdash_peers():
    out = []
    for p in tailnet_peers(ttl=60):
        if p["ip"] == TAILSCALE_IP:
            continue
        for u in _peer_urls(p):
            d = _fetch_stats(u)
            if d:
                out.append({"ip": p["ip"], "name": p["name"]})
                _PEER_CACHE[p["ip"]] = (time.time(), d, u)
                break
    _SPEERS.update(ts=time.time(), data=out)


def _peer_sampler():
    while True:
        try:
            _refresh_sysdash_peers()
        except Exception:
            pass
        time.sleep(15)


def sysdash_peers():
    return _SPEERS["data"]


def peer_stats(ip, ttl=1.5):
    """Cached proxy of a peer's /api/stats (only for known tailnet peers)."""
    peers = {p["ip"]: p for p in tailnet_peers()}
    if ip not in peers:
        return None
    c = _PEER_CACHE.get(ip)
    now = time.time()
    if c and now - c[0] < ttl:
        return c[1]
    urls = ([c[2]] if c else []) + _peer_urls(peers[ip])
    for u in urls:
        d = _fetch_stats(u)
        if d:
            _PEER_CACHE[ip] = (now, d, u)
            return d
    return None


_HISTORY_CACHE = {}  # runner_dir -> (ts, list)


def runner_history(runner_dir, n=5, ttl=45):
    """Recent finished jobs for a runner (result + duration), parsed cheaply
    from its _diag Worker logs (tail read + file stat)."""
    cached = _HISTORY_CACHE.get(runner_dir)
    now = time.time()
    if cached and now - cached[0] < ttl:
        return cached[1]
    out = []
    try:
        logs = sorted(glob.glob(os.path.join(runner_dir, "_diag", "Worker_*.log")),
                      key=os.path.getmtime, reverse=True)[:n]
        for lg in logs:
            st = os.stat(lg)
            dur = int(st.st_mtime - getattr(st, "st_birthtime", st.st_ctime))
            with open(lg, "rb") as f:
                head = f.read(262144).decode("utf-8", "ignore")
                if st.st_size > 16384:
                    f.seek(st.st_size - 16384)
                tail = f.read().decode("utf-8", "ignore")
            # large logs keep the result in the tail; small logs were fully read
            # into head (tail is then empty), so fall back to head.
            m = re.search(r"Job result after all job steps finish:\s*([A-Za-z]+)",
                          tail or head)
            wf = br = None
            # the job context serializes workflow_ref as a {"k":...,"v":...} pair
            wm = re.search(r'"workflow_ref",\s*"v":\s*"([^"]+)"', head)
            if wm:
                ref = wm.group(1)
                wf = ref.split("@")[0].rsplit("/", 1)[-1]
                if "@" in ref:
                    raw = ref.split("@", 1)[1]
                    pr = re.match(r"refs/pull/(\d+)/", raw)
                    if pr:
                        br = "PR #" + pr.group(1)
                    else:
                        br = raw.replace("refs/heads/", "").replace("refs/tags/", "")
            out.append({"result": (m.group(1) if m else None),
                        "dur": max(0, dur), "ago": int(now - st.st_mtime),
                        "workflow": wf, "branch": br})
    except Exception:
        pass
    _HISTORY_CACHE[runner_dir] = (now, out)
    return out


def runner_job(runner_dir):
    """Best-effort current-job context for a busy runner, read locally from the
    runner's last-written webhook event payload — no GitHub token needed."""
    ev = os.path.join(runner_dir, "_work", "_temp", "_github_workflow", "event.json")
    try:
        with open(ev, encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
        return None
    job = {}
    pr = d.get("pull_request") or {}
    if pr:
        job["pr"] = pr.get("number")
        job["pr_title"] = pr.get("title")
        job["pr_url"] = pr.get("html_url")
        job["branch"] = (pr.get("head") or {}).get("ref")
        job["base"] = (pr.get("base") or {}).get("ref")
    else:
        ref = d.get("ref") or ""
        if ref.startswith("refs/heads/"):
            job["branch"] = ref[len("refs/heads/"):]
        elif ref.startswith("refs/tags/"):
            job["tag"] = ref[len("refs/tags/"):]
    msg = ((d.get("head_commit") or {}).get("message") or "").splitlines()
    if msg:
        job["commit"] = msg[0][:90]
    wf = d.get("workflow")
    if isinstance(wf, str) and wf:
        job["workflow"] = wf.rsplit("/", 1)[-1]
    iss = d.get("issue") or {}
    if iss.get("number"):
        job["issue"] = iss.get("number")
        job["issue_url"] = iss.get("html_url")
    actor = (d.get("sender") or {}).get("login")
    if actor:
        job["actor"] = actor
    return {k: v for k, v in job.items() if v} or None


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
        entry = {
            "id": r["id"], "name": r["name"], "repo": r["repo"],
            "status": status,
            "uptime": int(now - since) if since else None,
            "url": url, "dir": d,
        }
        if status == "busy":
            j = runner_job(d) or {}
            j["elapsed"] = int(now - worker[d])  # job runtime from Worker start
            entry["job"] = j
        entry["history"] = runner_history(d)
        result.append(entry)
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
    # Like disk: psutil's `used` (active only) disagrees with its `percent`
    # (pressure = (total-available)/total, what Activity Monitor shows). Report
    # used = total - available so the GB value and the % use the same basis.
    mem_used = vm.total - vm.available
    mem_pct = round(mem_used / vm.total * 100, 1) if vm.total else 0.0
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
        "version": VERSION,
        "host": HOSTNAME,
        "localtime": time.strftime("%H:%M:%S"),
        "tz": time.strftime("%Z"),
        "tailscale_ip": TAILSCALE_IP,
        "ts": time.time(),
        "uptime": int(time.time() - psutil.boot_time()),
        "cpu": {"pct": cpu, "cores": cores,
                "count": _CPU["count"], "load": [round(x, 2) for x in load]},
        "mem": {"pct": mem_pct, "used": mem_used, "total": vm.total},
        "swap": {"pct": sw.percent, "used": sw.used, "total": sw.total},
        "disk": {"pct": disk_pct, "used": disk_used, "total": du.total},
        "net": dict(_NET),
        "battery": battery_info(),
        "hist": {"cpu": list(_HIST["cpu"]), "mem": list(_HIST["mem"])},
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


_CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".css": "text/css",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def handle_one_request(self):
        # clients (browser polls, headless screenshots) disconnect mid-response
        # all the time; don't dump a traceback for it.
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

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
        if self.path.startswith("/api/peers"):
            try:
                self._send(200, json.dumps(sysdash_peers()).encode(), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
            return
        if self.path.startswith("/api/peer"):
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                ip = (q.get("ip") or [""])[0]
                d = peer_stats(ip)
                if d is None:
                    self._send(404, b'{"error":"peer unreachable"}', "application/json")
                else:
                    self._send(200, json.dumps(d).encode(), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
            return
        req = self.path.split("?", 1)[0]
        path = "/index.html" if req in ("/", "") else req
        fp = os.path.normpath(os.path.join(HERE, path.lstrip("/")))
        if fp.startswith(HERE) and os.path.isfile(fp):
            with open(fp, "rb") as f:
                body = f.read()
            self._send(200, body, _CTYPES.get(os.path.splitext(fp)[1], "text/plain"))
        else:
            self._send(404, b"not found", "text/plain")


if __name__ == "__main__":
    threading.Thread(target=_cpu_sampler, daemon=True).start()
    threading.Thread(target=_peer_sampler, daemon=True).start()
    ThreadingHTTPServer.daemon_threads = True
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"sysdash on http://0.0.0.0:{PORT}  (tailscale {TAILSCALE_IP})")
    srv.serve_forever()
