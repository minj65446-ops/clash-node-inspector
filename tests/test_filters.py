# -*- coding: utf-8 -*-
"""v1.1 新增能力的验收测试：去重、过滤、配置裁剪。"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, os.path.join(ROOT, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export = _load("_export_under_test", "clash_export.py")
prune_mod = _load("_prune_under_test", "clash_prune.py")


def node(name, region="RO", delay=None, alive=None):
    if alive is None:
        alive = delay is not None
    return {"name": name, "region": region, "delay_ms": delay, "alive": alive}


class FingerprintTests(unittest.TestCase):
    def test_suffixes_normalize(self):
        for name in ["RO_speednode_0087 (2)", "RO_speednode_0087 #2",
                     "RO_speednode_0087 -2", "RO_speednode_0087"]:
            self.assertEqual(export.name_fingerprint(name), "ro_speednode_0087")

    def test_distinct_nodes_stay_distinct(self):
        self.assertNotEqual(export.name_fingerprint("NL_speednode_0004"),
                            export.name_fingerprint("NL_speednode_0005"))


class DedupeTests(unittest.TestCase):
    def test_keeps_plain_name_when_duplicate(self):
        nodes = [node("X (2)", delay=100), node("X", delay=300)]
        kept, dropped = export.dedupe_nodes(nodes)
        self.assertEqual([n["name"] for n in kept], ["X"])
        self.assertEqual([n["name"] for n in dropped], ["X (2)"])

    def test_keeps_faster_copy_among_suffixed(self):
        nodes = [node("X (1)", delay=300), node("X (2)", delay=120)]
        kept, _ = export.dedupe_nodes(nodes)
        self.assertEqual(kept[0]["name"], "X (2)")

    def test_no_duplicates_is_noop(self):
        nodes = [node("A", delay=10), node("B", delay=20)]
        kept, dropped = export.dedupe_nodes(nodes)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, [])


class FilterTests(unittest.TestCase):
    def test_keep_region(self):
        nodes = [node("a", "HK", 100), node("b", "JP", 100)]
        kept, dropped = export.apply_filters(nodes, keep_regions={"HK"})
        self.assertEqual([n["name"] for n in kept], ["a"])
        self.assertEqual(len(dropped), 1)

    def test_exclude_region(self):
        nodes = [node("a", "HK", 100), node("b", "RU", 100)]
        kept, _ = export.apply_filters(nodes, exclude_regions={"RU"})
        self.assertEqual([n["name"] for n in kept], ["a"])

    def test_max_delay_drops_dead_and_slow(self):
        nodes = [node("fast", "RO", 120), node("slow", "RO", 900),
                 node("dead", "RO", None)]
        kept, dropped = export.apply_filters(nodes, max_delay=400)
        self.assertEqual([n["name"] for n in kept], ["fast"])
        self.assertEqual(len(dropped), 2)

    def test_default_keeps_dead_nodes(self):
        nodes = [node("dead", "RO", None)]
        kept, dropped = export.apply_filters(nodes)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_parse_region_set(self):
        self.assertEqual(export.parse_region_set(" hk, JP ,"), {"HK", "JP"})
        self.assertEqual(export.parse_region_set(""), set())


PROFILE = """\
mixed-port: 7897
proxies:
- {name: "A", server: 1.1.1.1, port: 443, type: http}
- name: "B"
  server: 2.2.2.2
  port: 443
  type: http
- {name: "C", server: 3.3.3.3, port: 443, type: http}
proxy-groups:
- name: PROXY
  type: select
  proxies:
  - 自动选择
  - 香港
  - A
  - B
  - C
- name: 自动选择
  type: url-test
  url: https://www.gstatic.com/generate_204
  proxies:
  - A
  - B
  - C
- name: 香港
  type: select
  proxies:
  - B
rules:
- MATCH,PROXY
"""


class PruneTests(unittest.TestCase):
    def test_removes_dead_proxy_and_group_members(self):
        result, stats = prune_mod.prune(PROFILE, {"A", "C"})
        self.assertIn('name: "A"', result)
        self.assertNotIn('name: "B"', result)
        self.assertIn('server: 2.2.2.2', PROFILE)
        self.assertNotIn("server: 2.2.2.2", result)
        self.assertEqual(stats["removed_proxies"], ["B"])
        self.assertEqual(stats["removed_members"], 3)

    def test_emptied_group_is_dropped(self):
        result, stats = prune_mod.prune(PROFILE, {"A", "C"})
        self.assertEqual(stats["removed_groups"], ["香港"])
        self.assertNotIn("- name: 香港", result)

    def test_group_kept_when_any_member_survives(self):
        result, stats = prune_mod.prune(PROFILE, {"A", "B"})
        self.assertIn("- name: 自动选择", result)
        self.assertEqual(stats["removed_groups"], [])
        self.assertNotIn("- C", result.split("proxy-groups:")[1])

    def test_untouched_when_all_alive(self):
        result, stats = prune_mod.prune(PROFILE, {"A", "B", "C"})
        self.assertEqual(result, PROFILE)
        self.assertEqual(stats["removed_proxies"], [])
        self.assertEqual(stats["removed_members"], 0)

    def test_rules_section_preserved(self):
        result, _ = prune_mod.prune(PROFILE, {"A"})
        self.assertTrue(result.rstrip().endswith("- MATCH,PROXY"))


class ReportJsonTests(unittest.TestCase):
    def test_json_shape_matches_markdown(self):
        report = _load("_report_under_test", "proxy_report.py")
        items = [node("a", "HK", 100), node("b", "HK", 200),
                 node("c", "JP", None)]
        data = report.build_report_data(items)
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["alive"], 2)
        self.assertEqual(data["alive_rate"], "66.7%")
        self.assertEqual(data["median_delay"], "150 ms")
        self.assertEqual(len(data["recommendations"]), 2)
        self.assertEqual(data["recommendations"][0]["name"], "a")
        self.assertEqual([row["region"] for row in data["regions"]], ["HK", "JP"])

    def test_json_regions_have_all_keys(self):
        report = _load("_report_under_test2", "proxy_report.py")
        data = report.build_report_data([node("a", "HK", 100)])
        self.assertEqual(
            set(data["regions"][0]),
            {"region", "total", "alive", "alive_rate", "median_delay"},
        )


if __name__ == "__main__":
    unittest.main()
