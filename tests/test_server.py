"""Tests for mac-sysdash server.py — parsing, stats invariants, HTTP routes.

Run with a Python that has psutil:
    python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import types
import sqlite3
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402

# The real CodexBar snapshot lives in a TCC-protected Group Container; reading it
# from an interactive test run can pop a consent dialog and hang stats() (and thus
# the HTTP-route tests). Point the module defaults at nonexistent paths so no test
# ever touches it — the AI tests below set/restore their own fixtures.
server._CODEXBAR_SNAPSHOT = "/nonexistent/widget-snapshot.json"
server._CODEXBAR_HISTORY = "/nonexistent/codexbar-history"


def write_runner(parent, name="runner1", agent="mbp-ci",
                 url="https://github.com/acme/web", bom=True):
    d = os.path.join(parent, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".runner"), "w", encoding="utf-8") as f:
        if bom:
            f.write("﻿")  # GitHub writes .runner with a UTF-8 BOM
        json.dump({"agentName": agent, "gitHubUrl": url}, f)
    return d


def write_event(runner_dir, payload):
    ev = os.path.join(runner_dir, "_work", "_temp", "_github_workflow")
    os.makedirs(ev, exist_ok=True)
    with open(os.path.join(ev, "event.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


def write_worker_log(runner_dir, name, workflow_ref=None, result="Succeeded",
                     actor=None, head_ref=None, job=None):
    diag = os.path.join(runner_dir, "_diag")
    os.makedirs(diag, exist_ok=True)
    parts = ["[2026-06-22 10:00:00Z INFO Worker] Job started.\n"]
    if job is not None:  # GitHub serializes the job message near the top of the log
        parts.append('  "jobId": "abc",\n  "jobDisplayName": "%s",\n'
                     '  "jobName": "__default",\n' % job)
    if workflow_ref:
        parts.append('          "k": "workflow_ref",\n')
        parts.append('          "v": "%s"\n' % workflow_ref)
    if actor is not None:
        parts.append('          "k": "actor",\n          "v": "%s"\n' % actor)
    if head_ref is not None:
        parts.append('          "k": "head_ref",\n          "v": "%s"\n' % head_ref)
    if result:
        parts.append(
            "[2026-06-22 10:05:00Z INFO JobRunner] Job result after all job "
            "steps finish: %s\n" % result)
    parts.append("[2026-06-22 10:05:01Z INFO Worker] Job completed.\n")
    p = os.path.join(diag, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return p


class RunnerConfigTests(unittest.TestCase):
    def test_reads_name_and_repo_despite_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = write_runner(tmp, agent="mbp-webapp",
                             url="https://github.com/acme/web/")
            name, repo = server._read_runner_cfg(d)
            self.assertEqual(name, "mbp-webapp")
            self.assertEqual(repo, "acme/web")

    def test_non_runner_dir_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(server._read_runner_cfg(tmp))

    def test_falls_back_to_dirname_on_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "weird")
            os.makedirs(d)
            with open(os.path.join(d, ".runner"), "w") as f:
                f.write("not json")
            name, repo = server._read_runner_cfg(d)
            self.assertEqual(name, "weird")
            self.assertEqual(repo, "")


class RunnerJobTests(unittest.TestCase):
    def test_push_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_event(tmp, {"ref": "refs/heads/main",
                              "head_commit": {"message": "fix: thing\n\nbody"},
                              "workflow": ".github/workflows/ci.yml",
                              "sender": {"login": "octocat"}})
            j = server.runner_job(tmp)
            self.assertEqual(j["branch"], "main")
            self.assertEqual(j["commit"], "fix: thing")
            self.assertEqual(j["workflow"], "ci.yml")
            self.assertEqual(j["actor"], "octocat")

    def test_pull_request_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_event(tmp, {"pull_request": {
                "number": 42, "title": "Add checkout",
                "html_url": "https://github.com/acme/web/pull/42",
                "head": {"ref": "feature/x"}, "base": {"ref": "main"}}})
            j = server.runner_job(tmp)
            self.assertEqual(j["pr"], 42)
            self.assertEqual(j["pr_title"], "Add checkout")
            self.assertEqual(j["branch"], "feature/x")
            self.assertEqual(j["base"], "main")
            self.assertTrue(j["pr_url"].endswith("/pull/42"))

    def test_tag_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_event(tmp, {"ref": "refs/tags/v1.2.3"})
            self.assertEqual(server.runner_job(tmp)["tag"], "v1.2.3")

    def test_missing_event_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(server.runner_job(tmp))


class RunnerHistoryTests(unittest.TestCase):
    def setUp(self):
        server._HISTORY_CACHE.clear()

    def test_parses_result_workflow_and_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_worker_log(
                tmp, "Worker_20260622-100000-utc.log",
                workflow_ref="acme/web/.github/workflows/ci.yml@refs/heads/main",
                result="Succeeded")
            h = server.runner_history(tmp, ttl=0)
            self.assertEqual(len(h), 1)
            self.assertEqual(h[0]["result"], "Succeeded")
            self.assertEqual(h[0]["workflow"], "ci.yml")
            self.assertEqual(h[0]["branch"], "main")
            self.assertGreaterEqual(h[0]["dur"], 0)

    def test_parses_actor_and_pr_head_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_worker_log(
                tmp, "Worker_20260622-120000-utc.log",
                workflow_ref="acme/web/.github/workflows/ci.yml@refs/pull/628/merge",
                result="Succeeded", actor="octocat", head_ref="feature/login")
            h = server.runner_history(tmp, ttl=0)
            self.assertEqual(h[0]["branch"], "PR #628")
            self.assertEqual(h[0]["head"], "feature/login")
            self.assertEqual(h[0]["actor"], "octocat")

    def test_parses_job_display_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_worker_log(
                tmp, "Worker_20260622-140000-utc.log",
                workflow_ref="acme/web/.github/workflows/ci.yml@refs/heads/main",
                result="Succeeded", job="Build Android APKs")
            h = server.runner_history(tmp, ttl=0)
            self.assertEqual(h[0]["job"], "Build Android APKs")
            self.assertEqual(h[0]["workflow"], "ci.yml")  # both, job is not the workflow

    def test_job_is_none_when_log_has_no_job_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_worker_log(
                tmp, "Worker_20260622-150000-utc.log",
                workflow_ref="acme/web/.github/workflows/ci.yml@refs/heads/main",
                result="Succeeded")
            self.assertIsNone(server.runner_history(tmp, ttl=0)[0]["job"])

    def test_empty_actor_head_become_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_worker_log(
                tmp, "Worker_20260622-130000-utc.log",
                workflow_ref="acme/web/.github/workflows/ci.yml@refs/heads/main",
                result="Succeeded", actor="", head_ref="")
            h = server.runner_history(tmp, ttl=0)
            self.assertIsNone(h[0]["actor"])
            self.assertIsNone(h[0]["head"])

    def test_pull_request_ref_becomes_pr_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_worker_log(
                tmp, "Worker_20260622-110000-utc.log",
                workflow_ref="acme/web/.github/workflows/test.yml@refs/pull/2451/merge",
                result="Failed")
            h = server.runner_history(tmp, ttl=0)
            self.assertEqual(h[0]["branch"], "PR #2451")
            self.assertEqual(h[0]["result"], "Failed")

    def test_no_logs_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(server.runner_history(tmp, ttl=0), [])


class RunnerCurrentJobTests(unittest.TestCase):
    def test_reads_job_name_from_newest_worker_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = write_worker_log(tmp, "Worker_20260622-100000-utc.log",
                                   job="Test & Lint")
            new = write_worker_log(tmp, "Worker_20260622-120000-utc.log",
                                   job="Build Android APKs")
            os.utime(old, (1000, 1000))   # force deterministic mtime ordering
            os.utime(new, (2000, 2000))
            self.assertEqual(server.runner_current_job_name(tmp),
                             "Build Android APKs")

    def test_none_when_no_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(server.runner_current_job_name(tmp))

    def test_none_when_log_has_no_job_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_worker_log(tmp, "Worker_20260622-100000-utc.log",
                             workflow_ref="acme/web/.github/workflows/ci.yml"
                             "@refs/heads/main")
            self.assertIsNone(server.runner_current_job_name(tmp))


class TailnetPeerTests(unittest.TestCase):
    def test_returns_online_ipv4_peers_only(self):
        fake = {"Peer": {
            "a": {"Online": True, "TailscaleIPs": ["100.1.2.3", "fd7a::1"],
                  "HostName": "studio", "DNSName": "studio.tailnet.ts.net."},
            "b": {"Online": False, "TailscaleIPs": ["100.9.9.9"],
                  "HostName": "offline-box"}}}
        server._PEERS["ts"] = 0.0
        with mock.patch("server.subprocess.run",
                        return_value=types.SimpleNamespace(stdout=json.dumps(fake))):
            peers = server.tailnet_peers(ttl=0)
        self.assertEqual(peers, [{"ip": "100.1.2.3", "name": "studio",
                                  "dns": "studio.tailnet.ts.net", "os": "", "path": ""}])

    def test_peer_path_direct_or_relay(self):
        fake = {"Peer": {
            "a": {"Online": True, "TailscaleIPs": ["100.1.1.1"], "HostName": "a", "CurAddr": "192.168.1.5:41641"},
            "b": {"Online": True, "TailscaleIPs": ["100.1.1.2"], "HostName": "b", "Relay": "fra"}}}
        server._PEERS["ts"] = 0.0
        with mock.patch("server.subprocess.run",
                        return_value=types.SimpleNamespace(stdout=json.dumps(fake))):
            peers = server.tailnet_peers(ttl=0)
        self.assertEqual([p["path"] for p in peers], ["direct", "relay fra"])
        server._SPEERS["data"] = [{"ip": "100.1.1.1", "name": "a"}]
        server._PUSHED.clear()
        server._PUSHED["B"] = (server.time.time(), {"host": "B", "tailscale_ip": "100.1.1.2"})
        self.assertEqual({p["name"]: p["path"] for p in server.sysdash_peers()},
                         {"a": "direct", "B": "relay fra"})
        server._SPEERS["data"] = []
        server._PUSHED.clear()

    def test_offline_macs_listed_with_last_seen(self):
        fake = {"Peer": {
            "a": {"Online": True, "TailscaleIPs": ["100.1.2.3"], "HostName": "studio", "OS": "macOS"},
            "b": {"Online": False, "HostName": "laptop", "OS": "macOS", "LastSeen": "2026-10-06T10:07:33.1Z"},
            "c": {"Online": False, "HostName": "older", "OS": "macOS", "LastSeen": "2026-09-02T15:15:52Z"},
            "d": {"Online": False, "HostName": "never", "OS": "macOS", "LastSeen": "0001-01-01T00:00:00Z"},
            "e": {"Online": False, "HostName": "phone", "OS": "iOS", "LastSeen": "2026-10-06T10:00:00Z"}}}
        server._PEERS["ts"] = 0.0
        with mock.patch("server.subprocess.run",
                        return_value=types.SimpleNamespace(stdout=json.dumps(fake))):
            off = server.offline_macs()
        self.assertEqual([p["name"] for p in off], ["laptop", "older", "never"])
        self.assertEqual(off[0]["last_seen"], 1791281253)
        self.assertIsNone(off[2]["last_seen"])

    def test_net_link_kinds(self):
        ports = ("Hardware Port: Wi-Fi\nDevice: en0\n\n"
                 "Hardware Port: USB 10/100/1000 LAN\nDevice: en7\n\n"
                 "Hardware Port: iPhone USB\nDevice: en8\n")
        def fake(route):
            def run(cmd, **kw):
                return types.SimpleNamespace(stdout=route if cmd[0] == "/sbin/route" else ports)
            return run
        cases = [("interface: en0\n gateway: 192.168.1.1", "wifi"),
                 ("interface: en0\n gateway: 172.20.10.1", "hotspot"),
                 ("interface: en7\n gateway: 10.0.0.1", "ethernet"),
                 ("interface: en8\n gateway: 172.20.10.1", "hotspot"),
                 ("interface: utun4\n gateway: 10.2.0.1", "vpn"),
                 ("", "")]
        for route, kind in cases:
            with mock.patch("server.subprocess.run", side_effect=fake(route)):
                self.assertEqual(server.net_link()["type"], kind, route)

    def test_parse_ts(self):
        self.assertEqual(server._parse_ts("2026-10-06T10:07:33.123456789Z"), 1791281253)
        self.assertIsNone(server._parse_ts(None))
        self.assertIsNone(server._parse_ts("garbage"))

    def test_handles_tailscale_failure(self):
        server._PEERS["ts"] = 0.0
        with mock.patch("server.subprocess.run", side_effect=OSError):
            self.assertEqual(server.tailnet_peers(ttl=0), [])


class TailscaleBinTests(unittest.TestCase):
    def test_prefers_first_existing_candidate(self):
        app = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
        with mock.patch("server.os.access", side_effect=lambda p, m: p == app):
            self.assertEqual(server.tailscale_bin(), app)

    def test_resolves_symlink_to_real_binary(self):
        # The bundle CLI aborts when run through a symlink; run the target.
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(tmp, "Tailscale")
            open(real, "w").close()
            os.chmod(real, 0o755)
            link = os.path.join(tmp, "ts-link")  # not "tailscale": APFS is case-insensitive
            os.symlink(real, link)
            with mock.patch("server._TAILSCALE_CANDIDATES", (link,)):
                self.assertEqual(server.tailscale_bin(), os.path.realpath(real))

    def test_falls_back_to_path_then_bare_name(self):
        with mock.patch("server.os.access", return_value=False), \
                mock.patch("server.shutil.which", return_value="/x/tailscale"):
            self.assertEqual(server.tailscale_bin(), "/x/tailscale")
        with mock.patch("server.os.access", return_value=False), \
                mock.patch("server.shutil.which", return_value=None):
            self.assertEqual(server.tailscale_bin(), "tailscale")

    def test_callers_use_resolved_binary(self):
        server._PEERS["ts"] = 0.0
        with mock.patch("server.tailscale_bin", return_value="/x/tailscale"), \
                mock.patch("server.subprocess.run",
                           return_value=types.SimpleNamespace(stdout="{}")) as run:
            server.tailscale_ip()
            server.tailnet_peers(ttl=0)
        self.assertEqual([c.args[0][0] for c in run.call_args_list],
                         ["/x/tailscale", "/x/tailscale"])

    def test_missing_binary_degrades_to_local_only(self):
        server._PEERS["ts"] = 0.0
        with mock.patch("server.tailscale_bin", return_value="/nonexistent/tailscale"):
            self.assertEqual(server.tailscale_ip(), "")
            self.assertEqual(server.tailnet_peers(ttl=0), [])


class TailscaleIpCacheTests(unittest.TestCase):
    def tearDown(self):
        # Restore whatever the process started with so later tests aren't sticky.
        server._set_tailscale_ip(server.tailscale_ip())

    def test_empty_cli_output_is_empty_string(self):
        with mock.patch("server.subprocess.run",
                        return_value=types.SimpleNamespace(stdout="\n", stderr="")):
            self.assertEqual(server.tailscale_ip(), "")

    def test_stats_reflects_refreshed_cache(self):
        server._set_tailscale_ip("")
        self.assertEqual(server.stats()["tailscale_ip"], "")
        server._set_tailscale_ip("100.64.0.1")
        self.assertEqual(server.stats()["tailscale_ip"], "100.64.0.1")

    def test_set_normalizes_none_to_empty(self):
        server._set_tailscale_ip(None)
        self.assertEqual(server._current_tailscale_ip(), "")


class StatsTests(unittest.TestCase):
    def test_stats_has_expected_shape(self):
        s = server.stats()
        for key in ["version", "host", "localtime", "cpu", "mem", "disk",
                    "net", "battery", "hist", "runners", "top", "uptime"]:
            self.assertIn(key, s)
        self.assertEqual(s["version"], server.VERSION)
        self.assertIsInstance(s["runners"], list)
        for k in ("cpu", "mem", "disk"):           # history feeds the sparklines
            self.assertIn(k, s["hist"])

    def test_disk_used_is_total_minus_free(self):
        du = types.SimpleNamespace(total=460, used=300, free=60, percent=83.0)
        with mock.patch("server.psutil.disk_usage", return_value=du):
            s = server.stats()
        self.assertEqual(s["disk"]["used"], 460 - 60)        # 400, not psutil's 300
        self.assertEqual(s["disk"]["pct"], round(400 / 460 * 100, 1))

    def test_mem_used_is_total_minus_available(self):
        vm = types.SimpleNamespace(total=16, available=4, used=2, percent=99.0)
        with mock.patch("server.psutil.virtual_memory", return_value=vm):
            s = server.stats()
        self.assertEqual(s["mem"]["used"], 16 - 4)           # 12, not psutil's 2
        self.assertEqual(s["mem"]["pct"], round(12 / 16 * 100, 1))

    def test_disk_prefers_purgeable_inclusive_available(self):
        du = types.SimpleNamespace(total=460, used=300, free=6, percent=98.7)
        server._DISK_AVAIL["important"] = 60          # macOS-style available (incl purgeable)
        try:
            with mock.patch("server.psutil.disk_usage", return_value=du):
                s = server.stats()
        finally:
            server._DISK_AVAIL["important"] = None    # restore fallback for other tests
        self.assertEqual(s["disk"]["used"], 460 - 60)         # 400 (total-avail), not 454 (total-free)
        self.assertEqual(s["disk"]["pct"], round(400 / 460 * 100, 1))

    def test_history_disk_uses_same_basis_as_gauge(self):
        du = types.SimpleNamespace(total=460, used=300, free=6, percent=98.7)
        server._DISK_AVAIL["important"] = 60
        try:
            with mock.patch("server.psutil.disk_usage", return_value=du):
                self.assertEqual(server._disk_usage(), (400, 460))   # not (454, 460)
                s = server.stats()
        finally:
            server._DISK_AVAIL["important"] = None
        self.assertEqual(s["disk"]["used"], 400)

    def test_disk_important_available_never_crashes(self):
        v = server._disk_important_available("/System/Volumes/Data")
        self.assertTrue(v is None or (isinstance(v, int) and v > 0))


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server._STATE_DIR = self.tmp.name
        server._DB_PATH = os.path.join(self.tmp.name, "history.db")
        server._init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_history_insert_and_query(self):
        with mock.patch("server.time.time", return_value=1600000000):
            server._write_hist_db(10.0, 20.0, 30.0)
            
        with mock.patch("server.time.time", return_value=1600000060):
            res = server.history_stats("1h")
            self.assertIn("cpu", res)
            self.assertIn("mem", res)
            self.assertIn("disk", res)
            self.assertEqual(res["step"], 60)
            self.assertTrue(len(res["cpu"]) >= 2)
            # The last element should be the newly inserted or carried over.
            self.assertEqual(res["cpu"][-1], 10.0)
            self.assertEqual(res["mem"][-1], 20.0)

    def test_history_prune(self):
        # Insert a very old record
        with sqlite3.connect(server._DB_PATH) as conn:
            conn.execute("INSERT OR REPLACE INTO hist (ts, cpu, mem, disk) VALUES (?, ?, ?, ?)", (1000, 5.0, 5.0, 5.0))
        
        # Write a new record (simulating current time)
        with mock.patch("server.time.time", return_value=1000 + 8 * 24 * 3600):
            server._write_hist_db(10.0, 10.0, 10.0)
            
        # The old record should be deleted
        with sqlite3.connect(server._DB_PATH) as conn:
            c = conn.execute("SELECT COUNT(*) FROM hist")
            self.assertEqual(c.fetchone()[0], 1)

    def _seed_jobs(self, rows):
        now = int(server.time.time())
        with sqlite3.connect(server._DB_PATH) as conn:
            for i, (runner, job, result) in enumerate(rows):
                conn.execute(
                    "INSERT OR REPLACE INTO jobs (runner, logfile, ts, duration, result, "
                    "repo, workflow, job, branch, actor, head) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (runner, "log%d" % i, now - 3600, 60, result, "o/r", "wf", job,
                     "main", "me", "abc"))

    def test_flaky_detects_mixed_outcomes(self):
        self._seed_jobs([("/r1", "test", "Succeeded"), ("/r1", "test", "Failed"),
                         ("/r1", "test", "Succeeded"), ("/r1", "test", "Failed")])
        res = server.get_flaky_jobs()
        self.assertIn("/r1", res)
        self.assertEqual(res["/r1"][0]["job"], "test")
        self.assertEqual(res["/r1"][0]["runs"], 4)
        self.assertEqual(res["/r1"][0]["fail_rate"], 50)

    def test_flaky_ignores_always_pass_and_always_fail(self):
        self._seed_jobs([("/r1", "good", "Succeeded"), ("/r1", "good", "Succeeded"),
                         ("/r1", "good", "Succeeded"),
                         ("/r1", "broken", "Failed"), ("/r1", "broken", "Failed"),
                         ("/r1", "broken", "Failed")])
        self.assertEqual(server.get_flaky_jobs(), {})

    def test_disk_eta_none_when_history_thin(self):
        self.assertIsNone(server.disk_eta_days(80.0))

    def test_checks_state_machine(self):
        now = int(server.time.time())
        with sqlite3.connect(server._DB_PATH) as conn:
            conn.execute("INSERT INTO checks VALUES (?,?,?,?,?)", ("fresh", now-10, 60, 30, now-9999))
            conn.execute("INSERT INTO checks VALUES (?,?,?,?,?)", ("slow", now-100, 60, 30, now-9999))
            conn.execute("INSERT INTO checks VALUES (?,?,?,?,?)", ("dead", now-1000, 60, 30, now-9999))
        states = {c["name"]: c["state"] for c in server.get_checks()}
        self.assertEqual(states["fresh"], "up")     # 10 <= 90
        self.assertEqual(states["slow"], "late")    # 90 < 100 <= 150
        self.assertEqual(states["dead"], "down")    # 1000 > 150

    def test_app_group_collapses_helpers(self):
        self.assertEqual(server._app_group("Google Chrome Helper (Renderer)"), "Google Chrome")
        self.assertEqual(server._app_group("Claude Helper (GPU)"), "Claude")
        self.assertEqual(server._app_group("python3.9"), "python3.9")  # no helper → unchanged

    def test_baseline_flags_spike_and_thin_history(self):
        self.assertEqual(server.get_baseline(50, 50, 50), {})   # no history yet → {}
        now = int(server.time.time())
        with sqlite3.connect(server._DB_PATH) as conn:
            for i in range(40):
                conn.execute("INSERT INTO hist (ts,cpu,mem,disk) VALUES (?,?,?,?)",
                             (now - i*60, 40.0 + (i % 3), 60.0, 70.0))
        bl = server.get_baseline(95, 60, 70)   # cpu way above the ~41 baseline
        self.assertGreater(bl["cpu"]["z"], 3)
        self.assertNotIn("mem", bl)             # mem flat (std≈0) → omitted

    def test_net_daily_accumulates(self):
        server._NET_ACC["rx"], server._NET_ACC["tx"] = 1000, 500
        server._flush_net_daily()
        self.assertEqual(server.get_net_today(), {"rx": 1000, "tx": 500})
        self.assertEqual(server._NET_ACC["rx"], 0)   # reset after flush
        server._NET_ACC["rx"], server._NET_ACC["tx"] = 200, 0
        server._flush_net_daily()
        self.assertEqual(server.get_net_today(), {"rx": 1200, "tx": 500})

    def test_queue_stats_detects_back_to_back(self):
        now = int(server.time.time())
        # three 100s jobs starting back-to-back (gap ~0) => 2 contended of 3
        with sqlite3.connect(server._DB_PATH) as conn:
            for i, end in enumerate((now-800, now-700, now-600)):
                conn.execute("INSERT INTO jobs (runner, logfile, ts, duration, result) "
                             "VALUES (?,?,?,?,?)", ("/r", "log%d" % i, end, 100, "Succeeded"))
        q = server.get_queue_stats()["/r"]
        self.assertEqual(q["jobs"], 3)
        self.assertEqual(q["back_to_back"], 2)
        self.assertGreater(q["pressure"], 0)

    def test_queue_stats_ignores_spaced_out_jobs(self):
        now = int(server.time.time())
        with sqlite3.connect(server._DB_PATH) as conn:
            for i, end in enumerate((now-100000, now-50000, now-1000)):
                conn.execute("INSERT INTO jobs (runner, logfile, ts, duration, result) "
                             "VALUES (?,?,?,?,?)", ("/q", "log%d" % i, end, 60, "Succeeded"))
        q = server.get_queue_stats()["/q"]
        self.assertEqual(q["back_to_back"], 0)
        self.assertEqual(q["overlaps"], 0)

    def test_record_ping_upsert_and_reject(self):
        self.assertTrue(server.record_ping("job1", 120, 30))
        c = [x for x in server.get_checks() if x["name"] == "job1"][0]
        self.assertEqual((c["period"], c["grace"], c["state"]), (120, 30, "up"))
        self.assertFalse(server.record_ping("", None, None))   # empty name rejected
        # a second ping without params keeps the remembered period/grace
        self.assertTrue(server.record_ping("job1"))
        c = [x for x in server.get_checks() if x["name"] == "job1"][0]
        self.assertEqual((c["period"], c["grace"]), (120, 30))


class BatteryTests(unittest.TestCase):
    def test_battery_normalizes_unknown_time(self):
        b = types.SimpleNamespace(percent=83.6, power_plugged=True, secsleft=-2)
        with mock.patch("server.psutil.sensors_battery", return_value=b):
            info = server.battery_info()
        self.assertEqual(info["pct"], 84)
        self.assertTrue(info["plugged"])
        self.assertIsNone(info["secsleft"])

    def test_no_battery_returns_none(self):
        with mock.patch("server.psutil.sensors_battery", return_value=None):
            self.assertIsNone(server.battery_info())


class FormatStatusTableTests(unittest.TestCase):
    def test_format_table(self):
        s = {
            "host": "TestMac",
            "cpu": {"pct": 98.0},
            "mem": {"pct": 50.0},
            "disk": {"pct": 20.0},
            "runners": [
                {"name": "r1", "status": "busy", "job": {"name": "Build APK"}},
                {"name": "r2", "status": "idle", "history": [{"job": "Test"}]},
                {"name": "r3", "status": "offline"}
            ]
        }
        
        # With color
        out = server.format_status_table(s, use_color=True)
        self.assertIn("TestMac", out)
        self.assertIn("\033[31m! CPU: 98.0% !\033[0m", out) # cpu > 95 is red
        self.assertIn("\033[32mbusy    \033[0m Build APK", out)
        self.assertIn("\033[0midle    \033[0m Test", out)
        self.assertIn("\033[31moffline \033[0m", out)
        
        # Without color
        out_nc = server.format_status_table(s, use_color=False)
        self.assertNotIn("\033", out_nc)
        self.assertIn("! CPU: 98.0% !", out_nc)
        self.assertIn("busy     Build APK", out_nc)
        self.assertIn("idle     Test", out_nc)


class HttpRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path):
        return urllib.request.urlopen(self.base + path, timeout=10)

    def test_api_stats_json(self):
        r = self.get("/api/stats")
        self.assertEqual(r.status, 200)
        # The UI only talks to its own origin; a wildcard would let any web
        # page the viewer opens read this machine's stats.
        self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))
        d = json.load(r)
        self.assertEqual(d["version"], server.VERSION)
        for k in ("link", "macos", "chip"):
            self.assertIn(k, d)

    def test_api_history_json(self):
        r = self.get("/api/history?range=1h")
        self.assertEqual(r.status, 200)
        d = json.load(r)
        self.assertIn("cpu", d)
        self.assertIn("mem", d)
        self.assertIn("disk", d)
        self.assertIn("step", d)
        self.assertIn("t0", d)

    def test_api_peers_json(self):
        server._PEERS["ts"] = 0.0
        with mock.patch("server.subprocess.run",
                        return_value=types.SimpleNamespace(stdout="{}")):
            r = self.get("/api/peers")
        self.assertEqual(r.status, 200)
        self.assertIsInstance(json.load(r), list)

    def test_index_served(self):
        r = self.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("text/html", r.headers.get("Content-Type", ""))
        self.assertIn("Mac System Dashboard", r.read().decode("utf-8", "ignore"))

    def test_svg_content_type(self):
        r = self.get("/icon.svg")
        self.assertEqual(r.headers.get("Content-Type"), "image/svg+xml")

    def test_sw_content_type(self):
        r = self.get("/sw.js")
        self.assertEqual(r.headers.get("Content-Type"), "application/javascript")

    def test_unknown_path_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/does-not-exist")
        self.assertEqual(cm.exception.code, 404)

    def test_path_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/../server.py")
        self.assertEqual(cm.exception.code, 404)

    def test_peer_jobs_route_not_shadowed_by_peer(self):
        # /api/peer_jobs must answer with the jobs *list*; a prefix match on
        # /api/peer used to return the stats dict and break the peer timeline.
        server._PUSHED["Jobs"] = (server.time.time(), {"host": "Jobs", "cpu": {}})
        d = json.load(self.get("/api/peer_jobs?key=push:Jobs"))
        self.assertIsInstance(d, list)
        d = json.load(self.get("/api/peer?key=push:Jobs"))
        self.assertEqual(d["host"], "Jobs")

    def test_dotfiles_not_served(self):
        for path in ("/.github/workflows/ci.yml", "/.gitignore"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(path)
            self.assertEqual(cm.exception.code, 404)

    def test_static_path_rejects_sibling_prefix_dir(self):
        with mock.patch("server.HERE", "/srv/app"):
            self.assertIsNone(server._static_path("/../app2/secret.txt"))
            self.assertIsNone(server._static_path("/../app"))

    def test_disallowed_client_gets_403(self):
        with mock.patch("server.client_allowed", return_value=False):
            for path in ("/api/stats", "/"):
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    self.get(path)
                self.assertEqual(cm.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(self.base + "/api/push", data=b"{}", timeout=10)
            self.assertEqual(cm.exception.code, 403)

    def test_peer_history_route(self):
        with mock.patch("server.peer_by_key", return_value={"cpu": [1]}) as pk:
            d = json.load(self.get("/api/peer_history?key=ip:100.1.2.3&range=7d"))
        self.assertEqual(d, {"cpu": [1]})
        pk.assert_called_with("ip:100.1.2.3", endpoint="/api/history?range=7d")
        with mock.patch("server.peer_by_key", return_value=None):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get("/api/peer_history?key=push:x&range=bogus")
            self.assertEqual(cm.exception.code, 404)

    def test_offline_route(self):
        with mock.patch("server.offline_macs", return_value=[{"name": "ekos", "last_seen": 1}]):
            self.assertEqual(json.load(self.get("/api/offline")), [{"name": "ekos", "last_seen": 1}])

    def test_unreachable_route(self):
        with mock.patch("server.unreachable_peers", return_value=["ekos"]):
            self.assertEqual(json.load(self.get("/api/unreachable")), ["ekos"])

    def test_push_then_serve_over_http(self):
        server._PUSHED.clear()
        payload = {"version": "9.9.9", "host": "HttpPush", "cpu": {"pct": 1}}
        urllib.request.urlopen(self.base + "/api/push",
                               data=json.dumps(payload).encode(), timeout=10)
        peers = json.load(self.get("/api/peers"))
        self.assertIn("push:HttpPush", [p["key"] for p in peers])
        d = json.load(self.get("/api/peer?key=push:HttpPush"))
        self.assertEqual(d["host"], "HttpPush")
        self.assertIn("_age", d)


class PushTests(unittest.TestCase):
    def setUp(self):
        server._PUSHED.clear()

    def test_pushed_peer_listed_and_served_with_age(self):
        server._PUSHED["Box"] = (server.time.time(), {"host": "Box", "cpu": {}})
        self.assertIn("push:Box", [p["key"] for p in server.sysdash_peers()])
        d = server.peer_by_key("push:Box")
        self.assertEqual(d["host"], "Box")
        self.assertGreaterEqual(d["_age"], 0)

    def test_pushed_peer_expires(self):
        server._PUSHED["Old"] = (server.time.time() - 1000, {"host": "Old"})
        self.assertNotIn("push:Old", [p["key"] for p in server.sysdash_peers()])
        self.assertIsNone(server.peer_by_key("push:Old"))

    def test_unknown_key_returns_none(self):
        self.assertIsNone(server.peer_by_key("bogus"))

    def test_fetch_accepts_jobs_list_only_for_jobs_endpoint(self):
        class Resp:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return self.body
        jobs = json.dumps([{"runner": "/r", "ts": 1, "dur": 2}]).encode()
        with mock.patch("server.urllib.request.urlopen", return_value=Resp(jobs)):
            self.assertEqual(len(server._fetch_stats("http://x/api/jobs", endpoint="/api/jobs")), 1)
            self.assertIsNone(server._fetch_stats("http://x/api/stats"))   # a list is not a stats dict
        with mock.patch("server.urllib.request.urlopen", return_value=Resp(b"[]")):
            self.assertEqual(server._fetch_stats("http://x/api/jobs", endpoint="/api/jobs"), [])

    def test_peer_jobs_proxy_returns_list(self):
        peer = {"ip": "100.1.2.3", "name": "studio", "dns": ""}
        server._PEER_CACHE.clear()
        with mock.patch("server.tailnet_peers", return_value=[peer]), \
                mock.patch("server._fetch_stats",
                           side_effect=lambda u, timeout=6.0, endpoint="/api/stats":
                           [] if endpoint == "/api/jobs" else {"cpu": {}, "version": "1"}):
            self.assertEqual(server.peer_by_key("ip:100.1.2.3", endpoint="/api/jobs"), [])
            self.assertIn("cpu", server.peer_by_key("ip:100.1.2.3"))

    def test_push_only_peer_has_no_history(self):
        server._PUSHED["Box"] = (server.time.time(), {"host": "Box", "cpu": {}})
        self.assertIsNone(server.peer_by_key("push:Box", endpoint="/api/history?range=1h"))
        self.assertEqual(server.peer_by_key("push:Box", endpoint="/api/jobs"), [])

    def test_unreachable_lists_silent_macs_only(self):
        peers = [{"ip": "100.1.1.1", "name": "studio", "dns": "", "os": "macOS"},
                 {"ip": "100.1.1.2", "name": "phone", "dns": "", "os": "iOS"},
                 {"ip": "100.1.1.3", "name": "mini", "dns": "", "os": "macOS"},
                 {"ip": "100.1.1.4", "name": "pusher", "dns": "", "os": "macOS"}]
        up = {"cpu": {}, "version": "1"}
        server._PUSHED["Pusher"] = (server.time.time(), {"host": "Pusher", "tailscale_ip": "100.1.1.4"})
        with mock.patch("server.tailnet_peers", return_value=peers), \
                mock.patch("server._current_tailscale_ip", return_value="100.9.9.9"), \
                mock.patch("server._fetch_stats",
                           side_effect=lambda u, timeout=6.0, endpoint="/api/stats":
                           up if "100.1.1.3" in u else None):
            server._refresh_sysdash_peers()
        self.assertEqual([p["name"] for p in server._SPEERS["data"]], ["mini"])
        self.assertEqual(server.unreachable_peers(), ["studio"])

    def test_fetch_accepts_history_dict(self):
        class Resp:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return self.body
        with mock.patch("server.urllib.request.urlopen",
                        return_value=Resp(json.dumps({"cpu": [], "step": 60}).encode())):
            self.assertIn("cpu", server._fetch_stats("http://x/", endpoint="/api/history?range=1h"))
            self.assertIsNone(server._fetch_stats("http://x/"))   # not a stats dict

    def test_push_targets_accept_list(self):
        self.assertEqual(server._push_targets(""), [])
        self.assertEqual(server._push_targets("http://a/api/push"), ["http://a/api/push"])
        self.assertEqual(server._push_targets("http://a/api/push, http://b/api/push\nhttp://c/"),
                         ["http://a/api/push", "http://b/api/push", "http://c/"])

    def test_pusher_posts_to_every_target(self):
        with mock.patch("server.PUSH_TARGETS", ["http://a/", "http://b/"]), \
                mock.patch("server.cached_stats", return_value={"host": "x"}), \
                mock.patch("server._push_once") as once, \
                mock.patch("server.time.sleep", side_effect=StopIteration):
            with self.assertRaises(StopIteration):
                server._pusher()
        self.assertEqual([c.args[0] for c in once.call_args_list], ["http://a/", "http://b/"])


class AccessTests(unittest.TestCase):
    def test_tailnet_default_admits_loopback_and_tailnet_only(self):
        for ok in ("127.0.0.1", "::1", "100.101.102.103", "fd7a:115c:a1e0::1",
                   "::ffff:127.0.0.1", "::ffff:100.64.0.1"):
            self.assertTrue(server.client_allowed(ok, "tailnet"), ok)
        for bad in ("192.168.1.20", "10.0.0.5", "172.20.10.2", "8.8.8.8",
                    "fe80::1", "not-an-ip"):
            self.assertFalse(server.client_allowed(bad, "tailnet"), bad)

    def test_lan_adds_private_ranges_not_public(self):
        for ok in ("192.168.1.20", "10.0.0.5", "172.20.10.2", "fe80::1%en0", "100.64.0.1"):
            self.assertTrue(server.client_allowed(ok, "lan"), ok)
        self.assertFalse(server.client_allowed("8.8.8.8", "lan"))

    def test_any_and_unknown_modes(self):
        self.assertTrue(server.client_allowed("8.8.8.8", "any"))
        self.assertFalse(server.client_allowed("192.168.1.20", "typo"))   # falls back to tailnet

    def test_config_file_fills_unset_vars_only(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("# comment\nSYSDASH_T_A = 1\nSYSDASH_T_B=\"two\"\n"
                    "SYSDASH_T_C=file\nSYSDASH_T_D=filled\nPATH=/nope\njunk\n")
        env = {"SYSDASH_T_C": "env", "SYSDASH_T_D": ""}
        with mock.patch.dict(os.environ, env):
            server._load_config(f.name)
            self.assertEqual(os.environ["SYSDASH_T_A"], "1")
            self.assertEqual(os.environ["SYSDASH_T_B"], "two")
            self.assertEqual(os.environ["SYSDASH_T_C"], "env")      # real env wins
            self.assertEqual(os.environ["SYSDASH_T_D"], "filled")   # empty env counts as unset
            self.assertNotEqual(os.environ.get("PATH"), "/nope")    # only SYSDASH_* keys
            for k in ("SYSDASH_T_A", "SYSDASH_T_B"):
                os.environ.pop(k, None)
        os.unlink(f.name)

    def test_missing_config_file_is_ignored(self):
        server._load_config("/nonexistent/mac-sysdash/config")


class CliModeTests(unittest.TestCase):
    def test_status_path_fails_cleanly_not_with_a_crash(self):
        # The --status / __main__ path is NOT exercised by `import server`, so a
        # missing import there (e.g. the v1.9.0 `import sys` fix) slips past every
        # other test. Run it as a subprocess against an unreachable URL: it must
        # fail *cleanly* (handled error, exit 1), never crash with a traceback.
        import subprocess
        srv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "server.py")
        r = subprocess.run(
            [sys.executable, srv, "--status", "http://127.0.0.1:1/api/stats"],
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)        # connection refused -> exit 1
        self.assertNotIn("Traceback", r.stderr)     # handled, not crashed
        self.assertNotIn("NameError", r.stderr)
        self.assertIn("Error fetching", r.stderr)


class HistoryDbTests(unittest.TestCase):
    """The SQLite-backed history/jobs functions (point _DB_PATH at a temp file)."""
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._orig = server._DB_PATH
        server._DB_PATH = os.path.join(self._td.name, "h.db")
        server._init_db()

    def tearDown(self):
        server._DB_PATH = self._orig
        self._td.cleanup()

    def _conn(self):
        return sqlite3.connect(server._DB_PATH)

    def test_jobs_summary_counts_by_runner_and_day(self):
        now = int(time.time())
        rows = [
            ("rA", "w1", now, 10, "Succeeded", "r", "wf", "j", "b", "a", "h"),
            ("rA", "w2", now, 10, "Failed", "r", "wf", "j", "b", "a", "h"),
            ("rA", "w3", now, 10, "Cancelled", "r", "wf", "j", "b", "a", "h"),
            ("rB", "w1", now, 10, "Succeeded", "r", "wf", "j", "b", "a", "h"),
        ]
        with self._conn() as c:
            c.executemany(
                "INSERT INTO jobs (runner, logfile, ts, duration, result, repo, "
                "workflow, job, branch, actor, head) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        summ = server.get_jobs_summary()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))  # date(ts,'unixepoch') is UTC
        self.assertEqual(summ["rA"][day], {"succeeded": 1, "failed": 1, "other": 1})
        self.assertEqual(summ["rB"][day], {"succeeded": 1, "failed": 0, "other": 0})

    def test_history_stats_shape(self):
        now = int(time.time())
        base = now - (now % 60)
        with self._conn() as c:
            for i in range(5):
                c.execute("INSERT OR REPLACE INTO hist (ts, cpu, mem, disk) "
                          "VALUES (?,?,?,?)", (base - i * 60, 50.0, 60.0, 70.0))
        h = server.history_stats("1h")
        self.assertEqual(h["step"], 60)
        self.assertEqual(sorted(h.keys()), ["cpu", "disk", "mem", "step", "t0"])
        self.assertTrue(any(v == 50.0 for v in h["cpu"]))
        self.assertEqual(len(h["cpu"]), len(h["mem"]))

    def test_uptime_sla_in_range(self):
        now = int(time.time())
        base = now - (now % 60)
        with self._conn() as c:
            for i in range(10):
                c.execute("INSERT OR REPLACE INTO hist (ts, cpu, mem, disk) "
                          "VALUES (?,?,?,?)", (base - i * 60, 1, 1, 1))
        sla = server.uptime_sla()
        self.assertEqual(sorted(sla.keys()), ["d7", "h24"])
        for v in sla.values():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 100.0)


class AiStatsTests(unittest.TestCase):
    def test_history_fallback_survives_unreadable_snapshot(self):
        # Regression for the launchd TCC bug: a blocked/missing widget-snapshot
        # must NOT discard the history fallback (Claude/Codex).
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "claude.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 42}]},
                    {"name": "weekly", "entries": [{"usedPercent": 7}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = os.path.join(tmp, "missing-snapshot.json")
            server._AI_STATS_CACHE["ts"] = 0
            res = server._get_ai_stats()
            self.assertEqual(res.get("claude"), {"session": 42, "weekly": 7})

    def test_fda_status_blocked_when_snapshot_unreadable(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root bypasses file permissions")
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "snap.json")
            with open(p, "w") as f:
                f.write("{}")
            os.chmod(p, 0)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            server._CODEXBAR_SNAPSHOT = p
            st = server._ai_fda_status()
            self.assertTrue(st["blocked"])
            self.assertIn("path", st)

    def test_fda_status_not_blocked_when_snapshot_missing(self):
        self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
        server._CODEXBAR_SNAPSHOT = "/no/such/dir/snap.json"
        self.assertFalse(server._ai_fda_status()["blocked"])

    def test_tcc_read_times_out_without_blocking(self):
        # A read that blocks forever (the interactive TCC consent dialog) must
        # be abandoned after the timeout, not hang the caller.
        with tempfile.TemporaryDirectory() as tmp:
            fifo = os.path.join(tmp, "blocking.fifo")
            os.mkfifo(fifo)  # opening for read blocks until a writer appears
            start = time.monotonic()
            status, data = server._read_tcc_file(fifo, timeout=0.3)
            elapsed = time.monotonic() - start
            self.assertEqual(status, "timeout")
            self.assertIsNone(data)
            self.assertLess(elapsed, 2.0)

    def test_history_fallback_survives_blocked_snapshot_read(self):
        # Same invariant as the unreadable case, but for a *blocking* snapshot:
        # the timeout-guarded read is skipped and the history fallback survives.
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "claude.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 42}]},
                    {"name": "weekly", "entries": [{"usedPercent": 7}]}]}}, f)
            fifo = os.path.join(tmp, "snap.fifo")
            os.mkfifo(fifo)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            self.addCleanup(setattr, server, "_read_tcc_file", server._read_tcc_file)
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = fifo
            server._AI_STATS_CACHE["ts"] = 0
            orig = server._read_tcc_file
            server._read_tcc_file = lambda p, timeout=1.5: orig(p, timeout=0.3)
            res = server._get_ai_stats()
            self.assertEqual(res.get("claude"), {"session": 42, "weekly": 7})

    def test_parse_codexbar_usage(self):
        item = {"provider": "cursor", "usage": {
            "primary": {"usedPercent": 12, "resetsAt": "2026-08-01T00:00:00Z"},
            "secondary": {"usedPercent": 25, "resetsAt": "2026-08-08T00:00:00Z"},
        }}
        self.assertEqual(server._parse_codexbar_usage(item), {
            "session": 12, "weekly": 25,
            "session_reset": "2026-08-01T00:00:00Z",
            "weekly_reset": "2026-08-08T00:00:00Z",
        })

    def test_cli_merge_adds_cached_providers(self):
        self.addCleanup(lambda: server._AI_CLI.update(
            ts=0, data={}, order=[], busy=False))
        with server._AI_CLI_LOCK:
            server._AI_CLI.update(
                ts=time.time(),
                data={"cursor": {"session": 7, "weekly": 15}},
                order=["claude", "cursor"],
            )
        res = server._ai_cli_merge(
            {"claude": {"session": 10, "weekly": 20}}, snap_ok=False)
        self.assertEqual(res.get("claude"), {"session": 10, "weekly": 20})
        self.assertEqual(res.get("cursor"), {"session": 7, "weekly": 15})
        self.assertEqual(list(res.keys()), ["claude", "cursor"])

    def test_cli_merge_skipped_when_snapshot_ok(self):
        res = server._ai_cli_merge(
            {"claude": {"session": 1}}, snap_ok=True)
        self.assertEqual(res, {"claude": {"session": 1}})

    def test_corrupt_snapshot_uses_cli_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "claude.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 10}]},
                    {"name": "weekly", "entries": [{"usedPercent": 20}]}]}}, f)
            snap = os.path.join(tmp, "bad-snapshot.json")
            with open(snap, "w", encoding="utf-8") as f:
                f.write("{not json")
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            self.addCleanup(lambda: server._AI_CLI.update(
                ts=0, data={}, order=[], busy=False))
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = snap
            server._AI_STATS_CACHE["ts"] = 0
            with server._AI_CLI_LOCK:
                server._AI_CLI.update(
                    ts=time.time(),
                    data={"cursor": {"session": 7, "weekly": 15}},
                    order=["claude", "cursor"],
                )
            res = server._get_ai_stats()
            self.assertEqual(res.get("claude"), {"session": 10, "weekly": 20})
            self.assertEqual(res.get("cursor"), {"session": 7, "weekly": 15})


    def test_cli_merge_on_cache_hit_when_snapshot_blocked(self):
        self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={}, snap_ok=True)
        self.addCleanup(lambda: server._AI_CLI.update(
            ts=0, data={}, order=[], busy=False))
        server._AI_STATS_CACHE.update(
            ts=time.time(), data={"claude": {"session": 1}}, snap_ok=False)
        with server._AI_CLI_LOCK:
            server._AI_CLI.update(
                ts=time.time(),
                data={"cursor": {"session": 7}},
                order=["claude", "cursor"],
            )
        res = server._get_ai_stats()
        self.assertEqual(res.get("cursor"), {"session": 7})

    def test_ai_entry_is_stale(self):
        past1 = "2026-09-01T00:00:00Z"
        past2 = "2026-09-02T00:00:00Z"
        future1 = "2099-01-01T00:00:00Z"
        # All reset times in the past -> stale
        self.assertTrue(server._ai_entry_is_stale(
            {"session_reset": past1, "weekly_reset": past2}))
        # Single window in the past (lacks other window) -> stale
        self.assertTrue(server._ai_entry_is_stale({"session_reset": past1}))
        self.assertTrue(server._ai_entry_is_stale({"weekly_reset": past2}))
        # One reset in past, other unparseable/missing -> stale
        self.assertTrue(server._ai_entry_is_stale(
            {"session_reset": past1, "weekly_reset": "invalid"}))
        # Any reset time in future -> fresh (not stale)
        self.assertFalse(server._ai_entry_is_stale(
            {"session_reset": past1, "weekly_reset": future1}))
        self.assertFalse(server._ai_entry_is_stale(
            {"session_reset": future1, "weekly_reset": past1}))
        self.assertFalse(server._ai_entry_is_stale({"weekly_reset": future1}))
        # No reset timestamps or invalid object -> not stale
        self.assertFalse(server._ai_entry_is_stale({"session": 50}))
        self.assertFalse(server._ai_entry_is_stale({}))
        self.assertFalse(server._ai_entry_is_stale(None))

    def test_stale_history_replaced_by_cli_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "claude.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 10, "resetsAt": "2026-09-21T21:10:00Z"}]},
                    {"name": "weekly", "entries": [{"usedPercent": 20, "resetsAt": "2026-09-27T10:00:00Z"}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = os.path.join(tmp, "missing.json")
            server._AI_STATS_CACHE["ts"] = 0
            with server._AI_CLI_LOCK:
                server._AI_CLI.update(
                    ts=time.time(),
                    data={"claude": {"session": 80, "weekly": 40,
                                     "session_reset": "2099-01-01T00:00:00Z"}},
                    order=["claude"],
                )
            res = server._get_ai_stats()
            self.assertEqual(res.get("claude"), {
                "session": 80, "weekly": 40, "session_reset": "2099-01-01T00:00:00Z"
            })

    def test_fresh_history_wins_over_cli_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "codex.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 15, "resetsAt": "2099-01-01T00:00:00Z"}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = os.path.join(tmp, "missing.json")
            server._AI_STATS_CACHE["ts"] = 0
            with server._AI_CLI_LOCK:
                server._AI_CLI.update(
                    ts=time.time(),
                    data={"codex": {"session": 99, "weekly": 99}},
                    order=["codex"],
                )
            res = server._get_ai_stats()
            self.assertEqual(res.get("codex"), {
                "session": 15, "session_reset": "2099-01-01T00:00:00Z"
            })

    def test_stale_history_without_cli_value_returned_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "claude.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 10, "resetsAt": "2026-09-21T21:10:00Z"}]},
                    {"name": "weekly", "entries": [{"usedPercent": 20, "resetsAt": "2026-09-27T10:00:00Z"}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = os.path.join(tmp, "missing.json")
            server._AI_STATS_CACHE["ts"] = 0
            with server._AI_CLI_LOCK:
                server._AI_CLI.update(
                    ts=time.time(),
                    data={"cursor": {"session": 5}},
                    order=["claude", "cursor"],
                )
            with mock.patch("server._ai_cli_kick"):
                res = server._get_ai_stats()
            self.assertEqual(res.get("claude"), {
                "session": 10, "session_reset": "2026-09-21T21:10:00Z",
                "weekly": 20, "weekly_reset": "2026-09-27T10:00:00Z",
            })
            self.assertEqual(res.get("cursor"), {"session": 5})

    def test_refresh_ai_cli_fetches_stale_history_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            # claude is stale (resets in the past)
            with open(os.path.join(hist, "claude.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 10, "resetsAt": "2026-09-21T21:10:00Z"}]}]}}, f)
            # codex is fresh (reset in the future)
            with open(os.path.join(hist, "codex.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 10, "resetsAt": "2099-01-01T00:00:00Z"}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = os.path.join(tmp, "missing.json")
            with mock.patch("server._codexbar_enabled_providers",
                            return_value=["claude", "codex", "cursor"]), \
                 mock.patch("server._codexbar_fetch_providers",
                            return_value={"claude": {"session": 42}, "cursor": {"session": 12}}) as mock_fetch:
                server._refresh_ai_cli()
                self.assertTrue(mock_fetch.called)
                requested = mock_fetch.call_args[0][0]
                # Present but stale provider must be fetched
                self.assertIn("claude", requested)
                # Provider missing from history must be fetched
                self.assertIn("cursor", requested)
                # Fresh provider must NOT be fetched via slow CLI
                self.assertNotIn("codex", requested)
                # Cached CLI data was updated
                self.assertEqual(server._AI_CLI["data"].get("claude"), {"session": 42})
                self.assertEqual(server._AI_CLI["data"].get("cursor"), {"session": 12})

    def test_ai_cli_kick_triggered_when_stale_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "claude.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 10, "resetsAt": "2026-09-21T21:10:00Z"}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = os.path.join(tmp, "missing.json")
            # Last CLI attempt older than the loop period: a stale entry kicks.
            server._AI_STATS_CACHE["ts"] = 0
            with server._AI_CLI_LOCK:
                server._AI_CLI.update(
                    ts=time.time() - server._AI_CLI_PERIOD - 5,
                    data={"cursor": {"session": 5}},
                    order=["claude", "cursor"],
                )
            with mock.patch("server._ai_cli_kick") as mock_kick:
                server._get_ai_stats()
                mock_kick.assert_called_once()
            # A seconds-old attempt that could not answer for the stale provider
            # must not kick again on the next miss (the 30 s loop covers it).
            server._AI_STATS_CACHE["ts"] = 0
            with server._AI_CLI_LOCK:
                server._AI_CLI["ts"] = time.time()
            with mock.patch("server._ai_cli_kick") as mock_kick:
                server._get_ai_stats()
                mock_kick.assert_not_called()

    def test_invalid_reset_date_does_not_break_stats(self):
        # 2026-02-30 matches the timestamp regex but is no date; it used to raise
        # ValueError out of the cache-hit merge and 500 all of /api/stats.
        self.assertIsNone(server._parse_ts("2026-02-30T00:00:00Z"))
        self.assertFalse(server._ai_entry_is_stale({"session_reset": "2026-02-30T00:00:00Z"}))
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "claude.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 10, "resetsAt": "2026-02-30T00:00:00Z"}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = os.path.join(tmp, "missing.json")
            server._AI_STATS_CACHE["ts"] = 0
            with server._AI_CLI_LOCK:
                server._AI_CLI.update(ts=time.time(), data={"claude": {"session": 42}}, order=["claude"])
            with mock.patch("server._ai_cli_kick"):
                miss = server._get_ai_stats()
                hit = server._get_ai_stats()      # cache-hit merge path
            self.assertEqual(miss["claude"]["session"], 10)
            self.assertEqual(hit["claude"]["session"], 10)

    def test_no_enabled_providers_keeps_cli_data_and_marks_attempt(self):
        self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
        self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
        server._CODEXBAR_SNAPSHOT = "/nonexistent/widget-snapshot.json"
        with server._AI_CLI_LOCK:
            server._AI_CLI.update(ts=0, data={"claude": {"session": 42}}, order=["claude"])
        with mock.patch("server._codexbar_enabled_providers", return_value=[]), \
                mock.patch("server._codexbar_fetch_providers") as fetch:
            server._refresh_ai_cli()
        fetch.assert_not_called()
        self.assertNotEqual(server._AI_CLI["ts"], 0)
        self.assertEqual(server._AI_CLI["data"], {"claude": {"session": 42}})

    def test_malformed_history_file_skips_only_that_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "claude.json"), "w", encoding="utf-8") as f:
                f.write("{not json")
            with open(os.path.join(tmp, "codex.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "weekly", "entries": [{"usedPercent": 30}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            server._CODEXBAR_HISTORY = tmp + os.sep
            res = server._read_codexbar_history()
        self.assertNotIn("claude", res)
        self.assertEqual(res.get("codex"), {"weekly": 30})

    def test_empty_cli_result_does_not_retrigger_kick_when_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "codex.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 15, "resetsAt": "2099-01-01T00:00:00Z"}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = os.path.join(tmp, "missing.json")
            server._AI_STATS_CACHE["ts"] = 0
            with server._AI_CLI_LOCK:
                server._AI_CLI.update(
                    ts=time.time(),
                    data={},
                    order=["codex"],
                    busy=False,
                )
            with mock.patch("server._ai_cli_kick") as mock_kick:
                server._get_ai_stats()
                mock_kick.assert_not_called()

    def test_never_fetched_triggers_kick_even_if_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history")
            os.makedirs(hist)
            with open(os.path.join(hist, "codex.json"), "w", encoding="utf-8") as f:
                json.dump({"preferredAccountKey": "acc", "accounts": {"acc": [
                    {"name": "session", "entries": [{"usedPercent": 15, "resetsAt": "2099-01-01T00:00:00Z"}]}]}}, f)
            self.addCleanup(setattr, server, "_CODEXBAR_HISTORY", server._CODEXBAR_HISTORY)
            self.addCleanup(setattr, server, "_CODEXBAR_SNAPSHOT", server._CODEXBAR_SNAPSHOT)
            self.addCleanup(server._AI_STATS_CACHE.update, ts=0, data={})
            self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
            server._CODEXBAR_HISTORY = hist + os.sep
            server._CODEXBAR_SNAPSHOT = os.path.join(tmp, "missing.json")
            server._AI_STATS_CACHE["ts"] = 0
            with server._AI_CLI_LOCK:
                server._AI_CLI.update(
                    ts=0,
                    data={},
                    order=[],
                    busy=False,
                )
            with mock.patch("server._ai_cli_kick") as mock_kick:
                server._get_ai_stats()
                mock_kick.assert_called_once()

    def test_ai_cli_kick_with_non_empty_data_runs_refresh_only_when_not_busy(self):
        self.addCleanup(lambda: server._AI_CLI.update(ts=0, data={}, order=[], busy=False))
        # 1. Non-empty CLI data + busy=False -> real _ai_cli_kick spawns thread and runs _refresh_ai_cli
        with server._AI_CLI_LOCK:
            server._AI_CLI.update(ts=time.time(), data={"cursor": {"session": 5}}, order=["cursor"], busy=False)
        called = threading.Event()
        def fake_refresh():
            called.set()
        with mock.patch("server._refresh_ai_cli", side_effect=fake_refresh):
            server._ai_cli_kick()
            self.assertTrue(called.wait(timeout=2.0), "_refresh_ai_cli should run when not busy even if data is non-empty")
        # Wait for thread to clear busy flag
        for _ in range(100):
            with server._AI_CLI_LOCK:
                if not server._AI_CLI["busy"]:
                    break
            time.sleep(0.01)

        # 2. Non-empty CLI data + busy=True -> real _ai_cli_kick returns immediately without running _refresh_ai_cli
        with server._AI_CLI_LOCK:
            server._AI_CLI.update(ts=time.time(), data={"cursor": {"session": 5}}, order=["cursor"], busy=True)
        with mock.patch("server._refresh_ai_cli") as mock_refresh:
            server._ai_cli_kick()
            time.sleep(0.05)
            mock_refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
