#!/usr/bin/env python3
"""Generate a Markdown quality report for a JSON list of proxy nodes."""

from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any


def _is_integer(value: Any) -> bool:
    """Return whether value is an integer, excluding JSON booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


def _normalize_nodes(items: list[Any]) -> list[dict[str, Any]]:
    """Apply the field defaults and type constraints from TASK.md."""
    nodes: list[dict[str, Any]] = []
    for item in items:
        record = item if isinstance(item, dict) else {}

        name = record.get("name")
        if not isinstance(name, str):
            name = "UNKNOWN"

        region = record.get("region")
        if not isinstance(region, str) or region == "":
            region = "UNKNOWN"

        delay = record.get("delay_ms")
        if not _is_integer(delay):
            delay = None

        nodes.append(
            {
                "name": name,
                "region": region,
                "delay_ms": delay,
                "alive": record.get("alive", False) is True,
            }
        )
    return nodes


def _format_rate(alive: int, total: int) -> str:
    """Format a percentage to one decimal place using decimal half-up rounding."""
    if total == 0:
        return "0.0%"
    tenths, remainder = divmod(alive * 1000, total)
    if remainder * 2 >= total:
        tenths += 1
    return f"{tenths // 10}.{tenths % 10}%"


def _median_delay(nodes: list[dict[str, Any]]) -> str:
    values = sorted(
        node["delay_ms"]
        for node in nodes
        if node["alive"] and _is_integer(node["delay_ms"])
    )
    if not values:
        return "-"

    middle = len(values) // 2
    if len(values) % 2:
        median = values[middle]
    else:
        # The median is an integer or ends in .5. Round half away from zero,
        # which is the usual meaning of 四舍五入 (and avoids float precision).
        pair_sum = values[middle - 1] + values[middle]
        if pair_sum >= 0:
            median = (pair_sum + 1) // 2
        else:
            median = -((-pair_sum + 1) // 2)
    return f"{median} ms"


def build_report(items: list[Any]) -> str:
    """Build the report text for a JSON array."""
    nodes = _normalize_nodes(items)
    total = len(nodes)
    alive_nodes = [node for node in nodes if node["alive"]]
    alive_count = len(alive_nodes)

    summary = (
        "# 节点质量报告\n\n"
        f"- 总节点数: {total}\n"
        f"- 存活节点: {alive_count} ({_format_rate(alive_count, total)})\n"
        f"- 存活节点中位延迟: {_median_delay(nodes)}"
    )

    regions: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        regions.setdefault(node["region"], []).append(node)

    sorted_regions = sorted(
        regions.items(),
        key=lambda entry: (
            Fraction(
                -sum(1 for node in entry[1] if node["alive"]), len(entry[1])
            ),
            entry[0],
        ),
    )

    table_lines = [
        "| 地区 | 节点数 | 存活 | 存活率 | 中位延迟 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for region, region_nodes in sorted_regions:
        region_alive = sum(1 for node in region_nodes if node["alive"])
        table_lines.append(
            f"| {region} | {len(region_nodes)} | {region_alive} | "
            f"{_format_rate(region_alive, len(region_nodes))} | "
            f"{_median_delay(region_nodes)} |"
        )
    region_section = "## 按地区统计\n\n" + "\n".join(table_lines)

    recommendations = [
        node
        for node in nodes
        if node["alive"] and _is_integer(node["delay_ms"])
    ]
    recommendations.sort(key=lambda node: node["delay_ms"])
    recommendation_lines = [
        f"{index}. {node['name']} - {node['region']} - {node['delay_ms']} ms"
        for index, node in enumerate(recommendations[:3], start=1)
    ]
    recommendation_section = "## 推荐节点\n\n" + "\n".join(
        recommendation_lines
    )
    report = summary + "\n\n" + region_section + "\n\n" + recommendation_section
    if recommendation_lines:
        report += "\n"
    return report


def build_report_data(items: list[Any]) -> dict[str, Any]:
    """Build the machine-readable form of the report (mirrors build_report)."""
    nodes = _normalize_nodes(items)
    total = len(nodes)
    alive_nodes = [node for node in nodes if node["alive"]]

    regions: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        regions.setdefault(node["region"], []).append(node)

    region_rows = []
    for region, region_nodes in sorted(regions.items()):
        region_alive = sum(1 for node in region_nodes if node["alive"])
        region_rows.append(
            {
                "region": region,
                "total": len(region_nodes),
                "alive": region_alive,
                "alive_rate": _format_rate(region_alive, len(region_nodes)),
                "median_delay": _median_delay(region_nodes),
            }
        )

    recommendations = [
        {"name": node["name"], "region": node["region"], "delay_ms": node["delay_ms"]}
        for node in sorted(
            (n for n in nodes if n["alive"] and _is_integer(n["delay_ms"])),
            key=lambda n: n["delay_ms"],
        )[:3]
    ]

    return {
        "total": total,
        "alive": len(alive_nodes),
        "alive_rate": _format_rate(len(alive_nodes), total),
        "median_delay": _median_delay(nodes),
        "regions": region_rows,
        "recommendations": recommendations,
    }


def _reject_nonstandard_constant(value: str) -> None:    raise ValueError(f"non-standard JSON constant {value}")


def _error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="path to the node JSON file")
    parser.add_argument("--output", help="path for the Markdown report (default: stdout)")
    parser.add_argument("--json", action="store_true",
                        help="output machine-readable JSON instead of Markdown")
    args = parser.parse_args(argv)

    try:
        with open(args.input, "r", encoding="utf-8-sig") as source:
            data = json.load(source, parse_constant=_reject_nonstandard_constant)
    except OSError as exc:
        return _error(f"cannot read input file: {exc}")
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        return _error(f"invalid JSON: {exc}")

    if not isinstance(data, list):
        return _error("input JSON top level must be an array")

    if args.json:
        report = json.dumps(
            build_report_data(data), ensure_ascii=False, indent=2
        ) + "\n"
    else:
        report = build_report(data)
    if args.output is None:
        sys.stdout.write(report)
        return 0

    try:
        with open(args.output, "w", encoding="utf-8", newline="\n") as destination:
            destination.write(report)
    except OSError as exc:
        return _error(f"cannot write output file: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
