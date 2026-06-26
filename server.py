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
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("SYSDASH_PORT", "8765"))
VERSION = "1.12.0"

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
_HIST = {"cpu": [], "mem": [], "disk": [], "net_down": [], "net_up": []}
_HIST_LEN = 300  # ~5 min of 1s samples (sparkline uses the last 60; chart uses all)
_MIN_ACC = {"count": 0, "cpu": 0.0, "mem": 0.0, "disk": 0.0}
_prev_net = None

_STATE_DIR = os.path.join(HOME, ".local", "state", "sysdash")
_DB_PATH = os.path.join(_STATE_DIR, "history.db")

def _init_db():
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS hist (ts INTEGER PRIMARY KEY, cpu REAL, mem REAL, disk REAL)")
            conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
                runner TEXT, logfile TEXT, ts INTEGER, duration INTEGER, result TEXT,
                repo TEXT, workflow TEXT, job TEXT, branch TEXT, actor TEXT, head TEXT,
                PRIMARY KEY (runner, logfile)
            )""")
    except Exception:
        pass

def _write_hist_db(cpu, mem, disk):
    try:
        ts = int(time.time())
        ts -= ts % 60
        with sqlite3.connect(_DB_PATH, timeout=2) as conn:
            conn.execute("INSERT OR REPLACE INTO hist (ts, cpu, mem, disk) VALUES (?, ?, ?, ?)", (ts, round(cpu, 1), round(mem, 1), round(disk, 1)))
            conn.execute("DELETE FROM hist WHERE ts < ?", (ts - 7 * 24 * 3600,))
    except Exception:
        pass

def history_stats(rng="1h"):
    now = int(time.time())
    if rng == "7d":
        start = now - 7 * 24 * 3600
        step = 3600 # 1 hour
    elif rng == "24h":
        start = now - 24 * 3600
        step = 600 # 10 mins
    else: # default 1h
        start = now - 3600
        step = 60 # 1 min
    
    start -= start % step
    res = {"step": step, "t0": start, "cpu": [], "mem": [], "disk": []}
    try:
        with sqlite3.connect(_DB_PATH, timeout=2) as conn:
            c = conn.execute("SELECT (ts / ?) * ? as bucket, AVG(cpu), AVG(mem), AVG(disk) FROM hist WHERE ts >= ? GROUP BY bucket ORDER BY bucket", (step, step, start))
            rows = c.fetchall()
            
            buckets = {}
            for row in rows:
                buckets[row[0]] = (round(row[1], 1), round(row[2], 1), round(row[3], 1))
            
            t = start
            last_cpu, last_mem, last_disk = 0, 0, 0
            if rows:
                last_cpu, last_mem, last_disk = buckets.get(rows[0][0], (0,0,0))
            
            while t <= now:
                if t in buckets:
                    last_cpu, last_mem, last_disk = buckets[t]
                res["cpu"].append(last_cpu)
                res["mem"].append(last_mem)
                res["disk"].append(last_disk)
                t += step
    except Exception:
        pass
    
    return res

def uptime_sla():
    now = int(time.time())
    res = {"h24": 0.0, "d7": 0.0}
    try:
        with sqlite3.connect(_DB_PATH, timeout=2) as conn:
            c = conn.execute("SELECT MIN(ts), COUNT(*) FROM hist WHERE ts >= ?", (now - 24 * 3600,))
            row = c.fetchone()
            if row and row[0]:
                min_ts, count = row
                expected = max(1, (now - min_ts) // 60)
                res["h24"] = min(100.0, round((count / expected) * 100, 1))
            
            c = conn.execute("SELECT MIN(ts), COUNT(*) FROM hist")
            row = c.fetchone()
            if row and row[0]:
                min_ts, count = row
                expected = max(1, (now - min_ts) // 60)
                res["d7"] = min(100.0, round((count / expected) * 100, 1))
    except Exception:
        pass
    return res

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
            dpath = "/System/Volumes/Data" if os.path.isdir("/System/Volumes/Data") else "/"
            du = psutil.disk_usage(dpath)
            dp = round((du.total - du.free) / du.total * 100, 1) if du.total else 0.0
            _HIST["cpu"].append(_CPU["pct"])
            _HIST["mem"].append(mp)
            _HIST["disk"].append(dp)
            _HIST["net_down"].append(_NET["down"])
            _HIST["net_up"].append(_NET["up"])
            for k in _HIST:
                if len(_HIST[k]) > _HIST_LEN:
                    del _HIST[k][:-_HIST_LEN]
                    
            _MIN_ACC["cpu"] += _CPU["pct"]
            _MIN_ACC["mem"] += mp
            _MIN_ACC["disk"] += dp
            _MIN_ACC["count"] += 1
            if _MIN_ACC["count"] >= 60:
                c = _MIN_ACC["count"]
                _write_hist_db(_MIN_ACC["cpu"]/c, _MIN_ACC["mem"]/c, _MIN_ACC["disk"]/c)
                _MIN_ACC["count"] = 0
                _MIN_ACC["cpu"] = 0.0
                _MIN_ACC["mem"] = 0.0
                _MIN_ACC["disk"] = 0.0
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


def _jobs_sampler():
    """Periodically scan for new finished jobs and insert into SQLite."""
    while True:
        try:
            now = time.time()
            runners = discover_runners()
            with sqlite3.connect(_DB_PATH, timeout=2) as conn:
                for r in runners:
                    d = r["dir"]
                    repo = r["repo"]
                    # Get the most recent log file we processed for this runner
                    c = conn.execute("SELECT MAX(logfile) FROM jobs WHERE runner = ?", (d,))
                    row = c.fetchone()
                    last_log = row[0] if row and row[0] else ""
                    
                    logs = sorted(glob.glob(os.path.join(d, "_diag", "Worker_*.log")))
                    # Find all logs newer than last_log
                    new_logs = [lg for lg in logs if os.path.basename(lg) > last_log]
                    
                    for lg in new_logs:
                        st = os.stat(lg)
                        job = _parse_worker_log(lg, st)
                        if job["result"]:  # Only insert if the job is finished
                            conn.execute(
                                "INSERT OR IGNORE INTO jobs (runner, logfile, ts, duration, result, repo, workflow, job, branch, actor, head) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (d, os.path.basename(lg), int(st.st_mtime), job["dur"], job["result"], repo, job["workflow"], job["job"], job["branch"], job["actor"], job["head"])
                            )
                conn.commit()
        except Exception:
            pass
        time.sleep(60)


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


_PEERS = {"ts": 0, "data": []}
_AI_STATS_CACHE = {"ts": 0, "data": {}}

def _get_ai_stats():
    now = time.time()
    if now - _AI_STATS_CACHE["ts"] < 30:
        return _AI_STATS_CACHE["data"]
    res = {}
    base_path = os.path.expanduser("~/Library/Application Support/com.steipete.codexbar/history/")
    for m in ["claude", "codex"]:
        p = os.path.join(base_path, f"{m}.json")
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    pref = d.get("preferredAccountKey")
                    accs = d.get("accounts", {})
                    acc = accs.get(pref) if pref else (list(accs.values())[0] if accs else None)
                    if acc:
                        res[m] = {}
                        for tracker in acc:
                            name = tracker.get("name")
                            if name in ("session", "weekly"):
                                entries = tracker.get("entries", [])
                                if entries:
                                    res[m][name] = entries[-1].get("usedPercent", 0)
        except Exception:
            pass
    _AI_STATS_CACHE.update(ts=now, data=res)
    return res


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


def _fetch_stats(url, timeout=6.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        if isinstance(d, dict) and "cpu" in d and "version" in d:
            return d
    except Exception:
        pass
    return None


def _peer_urls(p, endpoint="/api/stats"):
    """Candidate stats URLs for a peer, HTTPS-serve first (only path that some
    nodes accept), then direct app ports for LAN peers without serve."""
    urls = []
    if p.get("dns"):
        urls.append(f"https://{p['dns']}{endpoint}")
    for port in _PEER_PORTS:
        urls.append(f"http://{p['ip']}:{port}{endpoint}")
    return urls


_SPEERS = {"ts": 0.0, "data": []}      # reachable sysdash peers: [{ip,name}]
_PEER_CACHE = {}                       # ip -> (ts, stats, working_url)


def _refresh_sysdash_peers():
    out = []
    for p in tailnet_peers(ttl=60):
        if p["ip"] == TAILSCALE_IP:
            continue
        for u in _peer_urls(p, "/api/stats"):
            d = _fetch_stats(u)
            if d:
                out.append({"ip": p["ip"], "name": p["name"]})
                _PEER_CACHE[f"{p['ip']}_/api/stats"] = (time.time(), d, u)
                break
    _SPEERS.update(ts=time.time(), data=out)


def _peer_sampler():
    while True:
        try:
            _refresh_sysdash_peers()
        except Exception:
            pass
        time.sleep(6)


# When this machine can't accept inbound connections, set SYSDASH_PUSH_TO to a
# hub's /api/push URL and it will POST its own stats there every few seconds.
PUSH_TO = os.environ.get("SYSDASH_PUSH_TO", "")


def _pusher():
    while True:
        try:
            data = json.dumps(cached_stats()).encode()
            req = urllib.request.Request(
                PUSH_TO, data=data, method="POST",
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=6).read()
        except Exception:
            pass
        time.sleep(0.5)


# Pushed peers: machines that can't accept inbound connections POST their stats
# here instead (see SYSDASH_PUSH_TO). Keyed by reported hostname.
_PUSHED = {}        # host -> (ts, stats)
_PUSH_LIST = 90     # keep listing a pushed peer (shown as stale) this long after its last push


def sysdash_peers():
    """All peers the browser can render: pull-discovered + push-reported, each
    with an opaque key the browser passes back to /api/peer."""
    out = [{"name": p["name"], "key": "ip:" + p["ip"]} for p in _SPEERS["data"]]
    seen = {p["name"] for p in out}
    now = time.time()
    for host, (ts, _d) in list(_PUSHED.items()):
        if now - ts < _PUSH_LIST and host not in seen:
            out.append({"name": host, "key": "push:" + host})
    return out


def peer_by_key(key, endpoint="/api/stats"):
    if key.startswith("push:"):
        if endpoint != "/api/stats":
            return []
        c = _PUSHED.get(key[5:])
        if c and time.time() - c[0] < _PUSH_LIST:
            d = dict(c[1])
            d["_age"] = int(time.time() - c[0])   # seconds since last push (for stale UI)
            return d
        return None
    if key.startswith("ip:"):
        return peer_stats(key[3:], endpoint=endpoint)
    return None


def peer_stats(ip, ttl=10.0, endpoint="/api/stats"):
    """Proxy a peer's endpoint (default /api/stats). Served from the cache that _peer_sampler keeps
    warm (peer links can be slow over Tailscale), so the browser never blocks on
    a slow fetch. Falls back to a one-off fetch, then to stale cache."""
    peers = {p["ip"]: p for p in tailnet_peers()}
    if ip not in peers:
        return None
    cache_key = f"{ip}_{endpoint}"
    c = _PEER_CACHE.get(cache_key)
    now = time.time()
    if c and now - c[0] < ttl:
        return c[1]
    urls = ([c[2]] if c else []) + _peer_urls(peers[ip], endpoint)
    for u in urls:
        d = _fetch_stats(u)
        if d:
            _PEER_CACHE[cache_key] = (now, d, u)
            return d
    return c[1] if c else None   # serve stale rather than nothing


_HISTORY_CACHE = {}  # runner_dir -> (ts, list)

# A Worker log records the display name of the job it ran (what GitHub's UI shows,
# e.g. "Build Android APKs") near its top. This is the ONLY local source that
# names the job: event.json is the workflow *trigger*, shared by every job in a
# run, so it can't tell one runner's job apart from another's in the same run.
_JOB_NAME_RE = re.compile(r'"jobDisplayName"\s*:\s*"([^"]+)"')


def _parse_worker_log(lg, st):
    dur = int(st.st_mtime - getattr(st, "st_birthtime", st.st_ctime))
    with open(lg, "rb") as f:
        head = f.read(262144).decode("utf-8", "ignore")
        if st.st_size > 16384:
            f.seek(st.st_size - 16384)
        tail = f.read().decode("utf-8", "ignore")
    m = re.search(r"Job result after all job steps finish:\s*([A-Za-z]+)", tail or head)
    wf = br = None
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
    am = re.search(r'"k":\s*"actor"\s*,\s*"v":\s*"([^"]*)"', head)
    hm = re.search(r'"k":\s*"head_ref"\s*,\s*"v":\s*"([^"]*)"', head)
    actor = am.group(1) if am and am.group(1) else None
    headref = hm.group(1) if hm and hm.group(1) else None
    jn = _JOB_NAME_RE.search(head)
    return {
        "result": m.group(1) if m else None,
        "dur": max(0, dur),
        "workflow": wf, "job": jn.group(1) if jn else None,
        "branch": br, "actor": actor, "head": headref
    }


def runner_history(runner_dir, n=20, ttl=45):
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
            job = _parse_worker_log(lg, st)
            job["ago"] = int(now - st.st_mtime)
            out.append(job)
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


def runner_current_job_name(runner_dir):
    """Display name of the job a busy runner is running *right now*, read from its
    newest Worker log (one Worker process == one job). event.json names the
    workflow run, not the job, so on a multi-job run split across runners every
    runner would otherwise look identical — this is what tells them apart."""
    try:
        logs = glob.glob(os.path.join(runner_dir, "_diag", "Worker_*.log"))
        if not logs:
            return None
        with open(max(logs, key=os.path.getmtime), "rb") as f:
            head = f.read(262144).decode("utf-8", "ignore")  # name sits near the top
    except Exception:
        return None
    m = _JOB_NAME_RE.search(head)
    return m.group(1) if m else None


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
            name = runner_current_job_name(d)  # the specific job, not just the run
            if name:
                j["name"] = name
            j["elapsed"] = int(now - worker[d])  # job runtime from Worker start
            entry["job"] = j
        entry["history"] = runner_history(d)
        result.append(entry)
    return result


def top_processes(n=8):
    procs_mem = []
    procs_cpu = []
    for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
        try:
            mem = p.info["memory_info"]
            rss = mem.rss if mem else 0
            cpu = p.info["cpu_percent"] or 0
            name = p.info["name"] or "?"
            procs_mem.append({"name": name, "rss": rss, "cpu": cpu})
            procs_cpu.append({"name": name, "rss": rss, "cpu": cpu})
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            pass
    procs_mem.sort(key=lambda x: x["rss"], reverse=True)
    procs_cpu.sort(key=lambda x: x["cpu"], reverse=True)
    return procs_mem[:n], procs_cpu[:n]


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
    t_mem, t_cpu = top_processes()
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
        "hist": {"cpu": list(_HIST["cpu"]), "mem": list(_HIST["mem"]),
                 "disk": list(_HIST["disk"]), "net_down": list(_HIST["net_down"]), "net_up": list(_HIST["net_up"])},
        "runners": runner_status(),
        "jobs_summary": get_jobs_summary(),
        "top": t_mem,
        "top_cpu": t_cpu,
        "ai": _get_ai_stats(),
        "sla": uptime_sla()
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


def get_jobs_summary(days=30):
    res = {}
    try:
        now = int(time.time())
        cutoff = now - days * 24 * 3600
        with sqlite3.connect(_DB_PATH, timeout=2) as conn:
            c = conn.execute(
                "SELECT runner, date(ts, 'unixepoch'), result "
                "FROM jobs WHERE ts >= ?", (cutoff,)
            )
            for row in c:
                r, d, res_str = row[0], row[1], row[2]
                if r not in res:
                    res[r] = {}
                if d not in res[r]:
                    res[r][d] = {"succeeded": 0, "failed": 0, "other": 0}
                if res_str and res_str.lower() == "succeeded":
                    res[r][d]["succeeded"] += 1
                elif res_str and res_str.lower() == "failed":
                    res[r][d]["failed"] += 1
                else:
                    res[r][d]["other"] += 1
    except Exception:
        pass
    return res


def get_jobs(days=30):
    res = []
    try:
        now = int(time.time())
        cutoff = now - days * 24 * 3600
        with sqlite3.connect(_DB_PATH, timeout=2) as conn:
            c = conn.execute(
                "SELECT runner, ts, duration, result, repo, workflow, job, branch, actor, head "
                "FROM jobs WHERE ts >= ? ORDER BY ts DESC", (cutoff,)
            )
            for row in c:
                res.append({
                    "runner": row[0], "ts": row[1], "dur": row[2], "result": row[3],
                    "repo": row[4], "workflow": row[5], "job": row[6], "branch": row[7],
                    "actor": row[8], "head": row[9]
                })
    except Exception:
        pass
    return res


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
        if self.path.startswith("/api/history"):
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                rng = (q.get("range") or ["1h"])[0]
                if rng not in ("1h", "24h", "7d"):
                    rng = "1h"
                body = json.dumps(history_stats(rng)).encode()
                self._send(200, body, "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
            return
        if self.path.startswith("/api/peers"):
            try:
                self._send(200, json.dumps(sysdash_peers()).encode(), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
            return
        if self.path.startswith("/api/jobs"):
            try:
                self._send(200, json.dumps(get_jobs()).encode(), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
            return
        if self.path.startswith("/api/peer"):
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                key = (q.get("key") or [""])[0]
                ip = (q.get("ip") or [""])[0]
                d = peer_by_key(key) if key else (peer_stats(ip) if ip else None)
                if d is None:
                    self._send(404, b'{"error":"peer unreachable"}', "application/json")
                else:
                    self._send(200, json.dumps(d).encode(), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
            return
        if self.path.startswith("/api/peer_jobs"):
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                key = (q.get("key") or [""])[0]
                ip = (q.get("ip") or [""])[0]
                d = peer_by_key(key, endpoint="/api/jobs") if key else (peer_stats(ip, endpoint="/api/jobs") if ip else None)
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

    def do_POST(self):
        if self.path.startswith("/api/push"):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n) if 0 < n <= 200000 else b"{}"
                d = json.loads(body.decode("utf-8", "ignore"))
                host = d.get("host") or "peer"
                _PUSHED[host] = (time.time(), d)
                self._send(200, b'{"ok":true}', "application/json")
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            return
        self._send(404, b"not found", "text/plain")


def format_status_table(s, use_color=True):
    def color(text, code):
        if not use_color: return text
        return f"\033[{code}m{text}\033[0m"
    out = []
    host = s.get("host", "Unknown")
    out.append(f"HOST: {host}")
    
    def format_pct(name, pct):
        txt = f"{name}: {pct}%"
        if pct >= 95:
            return color(f"! {txt} !", "31")
        return txt
        
    cpu = s.get("cpu", {}).get("pct", 0)
    mem = s.get("mem", {}).get("pct", 0)
    disk = s.get("disk", {}).get("pct", 0)
    out.append(" | ".join([format_pct("CPU", cpu), format_pct("MEM", mem), format_pct("DISK", disk)]))
    out.append("-" * 40)
    
    for r in s.get("runners", []):
        status = r.get("status", "offline")
        st_color = "32" if status == "busy" else ("31" if status == "offline" else "0")
        name = r.get("name", "?")
        job = r.get("job")
        job_name = job.get("name") if job else None
        if not job_name and r.get("history"):
            last = r["history"][0]
            job_name = last.get("job") or last.get("workflow") or "unknown"
            
        line = f"{name:<20} {color(status.ljust(8), st_color)}"
        if job_name:
            line += f" {job_name}"
        out.append(line)
        
    return "\n".join(out)

if __name__ == "__main__":
    if "--status" in sys.argv:
        try:
            import signal
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # exit quietly when piped (e.g. | head)
        except (ImportError, AttributeError, ValueError):
            pass
        idx = sys.argv.index("--status")
        url = f"http://localhost:{PORT}/api/stats"
        if len(sys.argv) > idx + 1 and not sys.argv[idx + 1].startswith("--"):
            url = sys.argv[idx + 1]
            
        is_json = "--json" in sys.argv
        use_color = sys.stdout.isatty() and not is_json
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as res:
                data = res.read().decode("utf-8")
                if is_json:
                    print(data)
                else:
                    s = json.loads(data)
                    print(format_status_table(s, use_color))
        except Exception as e:
            print(f"Error fetching status from {url}: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    _init_db()
    threading.Thread(target=_cpu_sampler, daemon=True).start()
    threading.Thread(target=_jobs_sampler, daemon=True).start()
    threading.Thread(target=_peer_sampler, daemon=True).start()
    if PUSH_TO:
        threading.Thread(target=_pusher, daemon=True).start()
    ThreadingHTTPServer.daemon_threads = True
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"sysdash on http://0.0.0.0:{PORT}  (tailscale {TAILSCALE_IP})")
    srv.serve_forever()
