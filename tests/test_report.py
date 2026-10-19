# -*- coding: utf-8 -*-
"""proxy_report.py 的验收测试（由项目发起方编写，实现方不得修改）。"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "proxy_report.py")
SAMPLE = os.path.join(ROOT, "sample_nodes.json")
TMPROOT = os.path.join(ROOT, "_tmp_tests")


def run(args, timeout=60):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
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


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def row_pattern(region, total, alive, rate, median):
    return re.compile(
        r"\|\s*%s\s*\|\s*%d\s*\|\s*%d\s*\|\s*%s\s*\|\s*%s\s*\|"
        % (re.escape(region), total, alive, re.escape(rate), re.escape(median))
    )


class TestProxyReport(unittest.TestCase):
    def tmp(self):
        os.makedirs(TMPROOT, exist_ok=True)
        d = os.path.join(TMPROOT, uuid.uuid4().hex)
        os.makedirs(d, exist_ok=True)
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def write_input(self, obj, raw=None):
        path = os.path.join(self.tmp(), "input.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(obj, ensure_ascii=False))
        return path

    def report(self):
        out = os.path.join(self.tmp(), "report.md")
        r = run(["--input", SAMPLE, "--output", out])
        self.assertEqual(r.returncode, 0, r.stderr)
        return read(out)

    def test_output_file_created(self):
        out = os.path.join(self.tmp(), "report.md")
        r = run(["--input", SAMPLE, "--output", out])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(out), "报告文件未生成")
        self.assertIn("# 节点质量报告", read(out))

    def test_stdout_when_no_output(self):
        r = run(["--input", SAMPLE])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("# 节点质量报告", r.stdout)
        self.assertIn("总节点数: 6", r.stdout)

    def test_summary_numbers(self):
        text = self.report()
        self.assertIn("- 总节点数: 6", text)
        self.assertIn("- 存活节点: 4 (66.7%)", text)
        self.assertIn("- 存活节点中位延迟: 230 ms", text)

    def test_region_table_values_and_order(self):
        text = self.report()
        self.assertIn("## 按地区统计", text)
        for args in (
            ("HK", 2, 2, "100.0%", "205 ms"),
            ("JP", 2, 1, "50.0%", "250 ms"),
            ("SG", 2, 1, "50.0%", "300 ms"),
        ):
            self.assertRegex(text, row_pattern(*args))
        self.assertLess(text.index("| JP |"), text.index("| SG |"), "地区排序不正确")

    def test_recommendations(self):
        text = self.report()
        self.assertIn("## 推荐节点", text)
        self.assertIn("1. HK-01 - HK - 200 ms", text)
        self.assertIn("2. HK-02 - HK - 210 ms", text)
        self.assertIn("3. JP-01 - JP - 250 ms", text)
        self.assertNotIn("4. ", text, "推荐节点最多 3 个")

    def test_empty_input(self):
        src = self.write_input(None, raw="[]")
        r = run(["--input", src])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("总节点数: 0", r.stdout)
        self.assertIn("存活节点: 0 (0.0%)", r.stdout)
        self.assertIn("存活节点中位延迟: -", r.stdout)

    def test_missing_fields_defaults(self):
        src = self.write_input([{"name": "X"}])
        r = run(["--input", src])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("总节点数: 1", r.stdout)
        self.assertIn("存活节点: 0 (0.0%)", r.stdout)
        self.assertRegex(r.stdout, row_pattern("UNKNOWN", 1, 0, "0.0%", "-"))

    def test_invalid_json_exit_2(self):
        src = self.write_input(None, raw="{not json")
        r = run(["--input", src])
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip(), "非法 JSON 时 stderr 应有错误信息")

    def test_missing_file_exit_2(self):
        r = run(["--input", os.path.join(ROOT, "no_such_file_12345.json")])
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())

    def test_top_level_not_array_exit_2(self):
        src = self.write_input({"a": 1})
        r = run(["--input", src])
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
