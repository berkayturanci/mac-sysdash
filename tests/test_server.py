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
            d = write_runner(tmp, agent="mbp-ingreview",
                             url="https://github.com/acme/web/")
            name, repo = server._read_runner_cfg(d)
            self.assertEqual(name, "mbp-ingreview")
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
                                  "dns": "studio.tailnet.ts.net"}])

    def test_handles_tailscale_failure(self):
        server._PEERS["ts"] = 0.0
        with mock.patch("server.subprocess.run", side_effect=OSError):
            self.assertEqual(server.tailnet_peers(ttl=0), [])


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
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "*")
        d = json.load(r)
        self.assertEqual(d["version"], server.VERSION)

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
        self.assertIn("Mac Dashboard", r.read().decode("utf-8", "ignore"))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
