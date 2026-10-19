# -*- coding: utf-8 -*-
"""clash_export.py 的验收测试 v2（由项目发起方编写，实现方不得修改）。"""
import http.server
import json
import os
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
SCRIPT = os.path.join(ROOT, "clash_export.py")
TMPROOT = os.path.join(ROOT, "_tmp_tests")


class FakeClash:
    """最小假 Clash 控制器（支持并发观测）。"""

    def __init__(self, proxies, delays=None, secret=None, invalid_json=False,
                 bad_shape=False, delay_401=False, delay_sleep=0.0, fail_first=None):
        self.proxies = proxies
        self.delays = delays or {}
        self.secret = secret
        self.invalid_json = invalid_json
        self.bad_shape = bad_shape
        self.delay_401 = delay_401
        self.delay_sleep = delay_sleep
        self.fail_first = dict(fail_first or {})
        self.delay_requests = []
        self.attempts = {}
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.httpd = None
        self.thread = None

    def start(self):
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, payload):
                if isinstance(payload, (dict, list)):
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    ctype = "application/json; charset=utf-8"
                else:
                    body = str(payload).encode("utf-8")
                    ctype = "text/plain; charset=utf-8"
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _auth_ok(self):
                if not fake.secret:
                    return True
                return self.headers.get("Authorization") == "Bearer " + fake.secret

            def do_GET(self):
                parts = urllib.parse.urlsplit(self.path)
                path = urllib.parse.unquote(parts.path)
                if path == "/proxies":
                    if not self._auth_ok():
                        return self._send(401, {"message": "unauthorized"})
                    if fake.invalid_json:
                        return self._send(200, "not a json at all")
                    if fake.bad_shape:
                        return self._send(200, {"proxies": []})
                    return self._send(200, {"proxies": fake.proxies})

                if path.startswith("/proxies/") and path.endswith("/delay"):
                    name = path[len("/proxies/"):-len("/delay")]
                    query = urllib.parse.parse_qs(parts.query)
                    with fake.lock:
                        fake.delay_requests.append({"name": name, "query": query})
                        fake.active += 1
                        fake.max_active = max(fake.max_active, fake.active)
                        fake.attempts[name] = fake.attempts.get(name, 0) + 1
                        attempt_no = fake.attempts[name]
                    try:
                        if fake.delay_sleep:
                            time.sleep(fake.delay_sleep)
                        if fake.delay_401 or not self._auth_ok():
                            return self._send(401, {"message": "unauthorized"})
                        if attempt_no <= fake.fail_first.get(name, 0):
                            return self._send(504, {"message": "An error occurred in the delay test"})
                        if name in fake.delays:
                            return self._send(200, {"delay": fake.delays[name]})
                        return self._send(504, {"message": "An error occurred in the delay test"})
                    finally:
                        with fake.lock:
                            fake.active -= 1

                return self._send(404, {"message": "not found"})

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    @property
    def url(self):
        host, port = self.httpd.server_address[:2]
        return "http://%s:%d" % (host, port)

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


def run(args, env_extra=None, timeout=120):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.pop("CLASH_SECRET", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


class Base(unittest.TestCase):
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

    def export(self, server, extra=None, env_extra=None, timeout=120):
        r = run(["--controller", server.url] + (extra or []), env_extra=env_extra, timeout=timeout)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout), r


PROXIES = {
    "GLOBAL": {"type": "Selector", "all": ["PROXY", "DIRECT"]},
    "PROXY": {"type": "Selector", "all": ["🇭🇰 香港 | HKG 5"]},
    "自动选择": {"type": "URLTest", "all": ["🇭🇰 香港 | HKG 5"]},
    "DIRECT": {"type": "Direct"},
    "REJECT": {"type": "Reject"},
    "🇭🇰 香港 | HKG 5": {"type": "Vmess", "history": [{"delay": 200}]},
    "SG_speednode_0001": {"type": "Http"},
    "JP-01": {"type": "Trojan"},
    "台湾 TW-01": {"type": "Vless"},
    "US_speednode_0131": {"type": "Http"},
    "NL_speednode_0009": {"type": "Http"},
    "": {"type": "Vmess"},
}

REGION_CASES = {
    "HongKong-01": "HK",
    "🇸🇬 新加坡 02": "SG",
    "Tokyo-03": "JP",
    "台北-04": "TW",
    "Seoul-05": "KR",
    "🇺🇸 美国 06": "US",
    "NL_speednode_0009": "NL",
    "RO_speednode_0041": "RO",
    "Germany-07": "DE",
    "United Kingdom-08": "GB",
    "France-09": "FR",
    "Canada-10": "CA",
    "Australia-11": "AU",
    "Russia-12": "RU",
    "Belarus-13": "UNKNOWN",
    "土耳其-14": "TR",
    "India-15": "IN",
    "迪拜-16": "AE",
    "🇨🇭CH_1|2.4MB/s": "CH",
    "🇮🇪 爱尔兰 | IRL #1": "IE",
}

CONCURRENCY_PROXIES = {"node-%02d" % i: {"type": "Http"} for i in range(8)}
CONCURRENCY_DELAYS = {"node-%02d" % i: 100 + i for i in range(8)}


class TestClashExport(Base):
    # ---------- v1.1 回归 ----------
    def test_filters_groups_and_builtins(self):
        server = self.start(proxies=PROXIES)
        data, _ = self.export(server)
        names = [item["name"] for item in data]
        for bad in ("GLOBAL", "PROXY", "自动选择", "DIRECT", "REJECT", ""):
            self.assertNotIn(bad, names)
        self.assertIn("🇭🇰 香港 | HKG 5", names)
        self.assertEqual(len(names), 6)

    def test_sorted_by_name(self):
        server = self.start(proxies=PROXIES)
        data, _ = self.export(server)
        names = [item["name"] for item in data]
        self.assertEqual(names, sorted(names))

    def test_no_delay_defaults(self):
        server = self.start(proxies=PROXIES)
        data, _ = self.export(server)
        for item in data:
            self.assertIs(item["alive"], False)
            self.assertIsNone(item["delay_ms"])

    def test_output_file_utf8(self):
        server = self.start(proxies=PROXIES)
        out = os.path.join(self.tmp(), "nodes.json")
        r = run(["--controller", server.url, "--output", out])
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 6)
        self.assertIn("🇭🇰 香港 | HKG 5", [d["name"] for d in data])

    def test_secret_header_sent(self):
        server = self.start(proxies=PROXIES, secret="s3cret")
        data, _ = self.export(server, env_extra={"CLASH_SECRET": "s3cret"})
        self.assertTrue(data)

    def test_wrong_secret_exit_2(self):
        server = self.start(proxies=PROXIES, secret="s3cret")
        r = run(["--controller", server.url, "--secret", "wrong"])
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())

    def test_delay_success_and_failure(self):
        server = self.start(
            proxies=PROXIES,
            delays={"🇭🇰 香港 | HKG 5": 123, "JP-01": 456},
            secret="s3cret",
        )
        data, _ = self.export(
            server,
            extra=["--test-delay"],
            env_extra={"CLASH_SECRET": "s3cret"},
        )
        by_name = {item["name"]: item for item in data}
        self.assertIs(by_name["🇭🇰 香港 | HKG 5"]["alive"], True)
        self.assertEqual(by_name["🇭🇰 香港 | HKG 5"]["delay_ms"], 123)
        self.assertIs(by_name["JP-01"]["alive"], True)
        self.assertEqual(by_name["JP-01"]["delay_ms"], 456)
        self.assertIs(by_name["SG_speednode_0001"]["alive"], False)
        self.assertIsNone(by_name["SG_speednode_0001"]["delay_ms"])

    def test_chinese_name_url_encoded_and_query_params(self):
        server = self.start(proxies=PROXIES, delays={"🇭🇰 香港 | HKG 5": 99})
        self.export(
            server,
            extra=["--test-delay", "--delay-url", "http://example.com/204", "--timeout", "1234"],
        )
        req = [r for r in server.delay_requests if r["name"] == "🇭🇰 香港 | HKG 5"]
        self.assertEqual(len(req), 1, "中文节点名未正确解码")
        self.assertEqual(req[0]["query"].get("url"), ["http://example.com/204"])
        self.assertEqual(req[0]["query"].get("timeout"), ["1234"])

    def test_empty_proxies(self):
        server = self.start(proxies={})
        r = run(["--controller", server.url])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [])

    def test_controller_unreachable_exit_2(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        r = run(["--controller", "http://127.0.0.1:%d" % port], timeout=30)
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())

    def test_invalid_json_response_exit_2(self):
        server = self.start(proxies=PROXIES, invalid_json=True)
        r = run(["--controller", server.url])
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())

    def test_bad_response_shape_exit_2(self):
        server = self.start(proxies=PROXIES, bad_shape=True)
        r = run(["--controller", server.url])
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())

    def test_delay_401_exit_2(self):
        server = self.start(proxies=PROXIES, delay_401=True)
        r = run(["--controller", server.url, "--test-delay"])
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())

    # ---------- v2：地区识别 ----------
    def test_region_inference_v2(self):
        proxies = {name: {"type": "Vmess"} for name in REGION_CASES}
        server = self.start(proxies=proxies)
        data, _ = self.export(server)
        got = {item["name"]: item["region"] for item in data}
        for name, expected in REGION_CASES.items():
            self.assertEqual(got.get(name), expected, "地区推断错误: %s" % name)

    def test_region_no_false_positive(self):
        proxies = {"Russia-01": {"type": "Vmess"}, "Belarus-01": {"type": "Vmess"}}
        server = self.start(proxies=proxies)
        data, _ = self.export(server)
        got = {item["name"]: item["region"] for item in data}
        self.assertEqual(got["Russia-01"], "RU")
        self.assertEqual(got["Belarus-01"], "UNKNOWN")

    # ---------- v2：并发延迟 ----------
    def test_concurrency_default_is_sequential(self):
        server = self.start(
            proxies=CONCURRENCY_PROXIES,
            delays=CONCURRENCY_DELAYS,
            delay_sleep=0.05,
        )
        data, _ = self.export(server, extra=["--test-delay"])
        self.assertEqual(server.max_active, 1, "默认并发应为 1")
        self.assertEqual(len(data), 8)

    def test_concurrency_parallel(self):
        server = self.start(
            proxies=CONCURRENCY_PROXIES,
            delays=CONCURRENCY_DELAYS,
            delay_sleep=0.15,
        )
        data, _ = self.export(server, extra=["--test-delay", "--concurrency", "4"])
        self.assertGreaterEqual(server.max_active, 2, "并发未生效")
        self.assertLessEqual(server.max_active, 4, "并发数超过 --concurrency 限制")
        by_name = {item["name"]: item for item in data}
        for name, delay in CONCURRENCY_DELAYS.items():
            self.assertIs(by_name[name]["alive"], True)
            self.assertEqual(by_name[name]["delay_ms"], delay)
        names = [item["name"] for item in data]
        self.assertEqual(names, sorted(names), "并发下输出仍须按名称排序")

    def test_concurrency_invalid_exit_2(self):
        server = self.start(proxies=PROXIES)
        for bad in ("0", "17", "-1", "abc"):
            r = run(["--controller", server.url, "--test-delay", "--concurrency", bad])
            self.assertEqual(r.returncode, 2, "--concurrency=%s 应退出 2" % bad)
            self.assertTrue(r.stderr.strip())


RETRY_PROXIES = {
    "node-a": {"type": "Http"},
    "node-b": {"type": "Http"},
    "flaky": {"type": "Http"},
}
RETRY_DELAYS = {"node-a": 100, "node-b": 101, "flaky": 102}


class TestRetry(Base):
    def test_retry_recovers_after_failures(self):
        server = self.start(proxies=RETRY_PROXIES, delays=RETRY_DELAYS, fail_first={"flaky": 1})
        data, _ = self.export(server, extra=["--test-delay", "--retry", "1"])
        by_name = {item["name"]: item for item in data}
        self.assertIs(by_name["flaky"]["alive"], True)
        self.assertEqual(by_name["flaky"]["delay_ms"], 102)
        self.assertEqual(server.attempts["flaky"], 2)
        self.assertEqual(server.attempts["node-a"], 1)

    def test_no_retry_by_default(self):
        server = self.start(proxies=RETRY_PROXIES, delays=RETRY_DELAYS, fail_first={"flaky": 1})
        data, _ = self.export(server, extra=["--test-delay"])
        by_name = {item["name"]: item for item in data}
        self.assertIs(by_name["flaky"]["alive"], False)
        self.assertIsNone(by_name["flaky"]["delay_ms"])
        self.assertEqual(server.attempts["flaky"], 1)

    def test_retry_exhausted_marks_dead(self):
        server = self.start(proxies=RETRY_PROXIES, delays=RETRY_DELAYS, fail_first={"flaky": 3})
        data, _ = self.export(server, extra=["--test-delay", "--retry", "2"])
        by_name = {item["name"]: item for item in data}
        self.assertIs(by_name["flaky"]["alive"], False)
        self.assertEqual(server.attempts["flaky"], 3)

    def test_retry_invalid_exit_2(self):
        server = self.start(proxies=RETRY_PROXIES)
        for bad in ("6", "-1", "abc"):
            r = run(["--controller", server.url, "--test-delay", "--retry", bad])
            self.assertEqual(r.returncode, 2, "--retry=%s 应退出 2" % bad)
            self.assertTrue(r.stderr.strip())

    def test_retry_401_aborts_without_retry(self):
        server = self.start(proxies=RETRY_PROXIES, delays=RETRY_DELAYS, delay_401=True)
        r = run(["--controller", server.url, "--test-delay", "--retry", "2"])
        self.assertEqual(r.returncode, 2)
        self.assertEqual(sum(server.attempts.values()), 1, "401 不应重试")

    def test_retry_respects_concurrency(self):
        proxies = {"n%02d" % i: {"type": "Http"} for i in range(6)}
        delays = {"n%02d" % i: 200 + i for i in range(6)}
        server = self.start(
            proxies=proxies,
            delays=delays,
            fail_first={"n%02d" % i: 1 for i in range(6)},
            delay_sleep=0.05,
        )
        data, _ = self.export(server, extra=["--test-delay", "--retry", "1", "--concurrency", "2"])
        self.assertLessEqual(server.max_active, 2, "重试不得突破 --concurrency 限制")
        for item in data:
            self.assertIs(item["alive"], True)
        for name in delays:
            self.assertEqual(server.attempts[name], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
