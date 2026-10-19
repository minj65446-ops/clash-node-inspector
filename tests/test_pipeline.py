# -*- coding: utf-8 -*-
"""pipeline.py 的验收测试（由项目发起方编写，实现方不得修改）。"""
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.parse
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "pipeline.py")
TMPROOT = os.path.join(ROOT, "_tmp_tests")


class FakeClash:
    def __init__(self, proxies, delays=None, fail_first=None):
        self.proxies = proxies
        self.delays = delays or {}
        self.fail_first = dict(fail_first or {})
        self.attempts = {}
        self.lock = threading.Lock()
        self.httpd = None

    def start(self):
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, payload):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parts = urllib.parse.urlsplit(self.path)
                path = urllib.parse.unquote(parts.path)
                if path == "/proxies":
                    return self._send(200, {"proxies": fake.proxies})
                if path.startswith("/proxies/") and path.endswith("/delay"):
                    name = path[len("/proxies/"):-len("/delay")]
                    with fake.lock:
                        fake.attempts[name] = fake.attempts.get(name, 0) + 1
                        attempt = fake.attempts[name]
                    if attempt <= fake.fail_first.get(name, 0):
                        return self._send(504, {"message": "delay failed"})
                    if name in fake.delays:
                        return self._send(200, {"delay": fake.delays[name]})
                    return self._send(504, {"message": "delay failed"})
                return self._send(404, {"message": "not found"})

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    @property
    def url(self):
        host, port = self.httpd.server_address[:2]
        return "http://%s:%d" % (host, port)

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


def run_pipeline(args, cwd=None, timeout=180):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


class TestPipeline(unittest.TestCase):
    def tmp(self):
        os.makedirs(TMPROOT, exist_ok=True)
        d = os.path.join(TMPROOT, uuid.uuid4().hex)
        os.makedirs(d, exist_ok=True)
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def start(self, **kwargs):
        server = FakeClash(**kwargs).start()
        self.addCleanup(server.stop)
        return server

    def test_creates_nodes_and_report(self):
        server = self.start(
            proxies={"A-1": {"type": "Vmess"}, "B-2": {"type": "Http"}, "C-3": {"type": "Trojan"}},
            delays={"A-1": 111, "B-2": 222, "C-3": 333},
        )
        out = self.tmp()
        r = run_pipeline([
            "--controller", server.url, "--test-delay",
            "--concurrency", "3", "--output-dir", out,
        ])
        self.assertEqual(r.returncode, 0, r.stderr)
        nodes_path = os.path.join(out, "nodes.json")
        report_path = os.path.join(out, "report.md")
        self.assertTrue(os.path.exists(nodes_path), "nodes.json 未生成")
        self.assertTrue(os.path.exists(report_path), "report.md 未生成")

        with open(nodes_path, encoding="utf-8") as f:
            nodes = json.load(f)
        self.assertEqual(len(nodes), 3)
        self.assertTrue(all(n["alive"] for n in nodes))

        with open(report_path, encoding="utf-8") as f:
            report = f.read()
        self.assertIn("节点质量报告", report)
        self.assertIn("总节点数: 3", report)
        self.assertIn("存活节点: 3 (100.0%)", report)

        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, "stdout 应恰好一行摘要: %r" % r.stdout)
        self.assertRegex(lines[0], r"^导出 3 个节点（存活 3），报告: .*report\.md$")

    def test_output_dir_created_recursively(self):
        server = self.start(proxies={"A": {"type": "Vmess"}})
        base = self.tmp()
        out = os.path.join(base, "a", "b", "c")
        r = run_pipeline(["--controller", server.url, "--output-dir", out])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(out, "report.md")))

    def test_default_output_dir_relative_to_cwd(self):
        server = self.start(proxies={"A": {"type": "Vmess"}}, delays={"A": 100})
        workdir = self.tmp()
        r = run_pipeline(["--controller", server.url, "--test-delay"], cwd=workdir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(workdir, "out", "report.md")),
                        "默认输出目录 out/ 未在 cwd 下创建")

    def test_controller_unreachable_exit_2(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        r = run_pipeline(["--controller", "http://127.0.0.1:%d" % port, "--output-dir", self.tmp()])
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())

    def test_retry_passed_through(self):
        server = self.start(
            proxies={"flaky": {"type": "Http"}, "ok": {"type": "Http"}},
            delays={"flaky": 150, "ok": 100},
            fail_first={"flaky": 1},
        )
        out = self.tmp()
        r = run_pipeline([
            "--controller", server.url, "--test-delay", "--retry", "1", "--output-dir", out,
        ])
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(out, "report.md"), encoding="utf-8") as f:
            report = f.read()
        self.assertIn("存活节点: 2 (100.0%)", report)
        self.assertEqual(server.attempts["flaky"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
