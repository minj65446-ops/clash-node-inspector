#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run Clash export and proxy report generation as one pipeline."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


def _load_module(module_name, script_path):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError("无法加载模块文件: %s" % script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report_script_path(project_dir):
    # 支持两种布局：同目录（开源仓库扁平结构）或 ../proxy_report（demo 结构）
    flat = project_dir / "proxy_report.py"
    if flat.is_file():
        return flat
    return project_dir.parent / "proxy_report" / "proxy_report.py"

def _error(message):
    print("错误：" + str(message), file=sys.stderr)
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", default="http://127.0.0.1:9097")
    parser.add_argument("--secret", default=os.environ.get("CLASH_SECRET", ""))
    parser.add_argument("--output-dir", default="out")
    parser.add_argument("--test-delay", action="store_true")
    parser.add_argument("--delay-url", default="http://www.gstatic.com/generate_204")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--retry", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=5000)
    parser.add_argument("--csv", action="store_true", help="额外输出 out/nodes.csv")
    args = parser.parse_args(argv)

    project_dir = Path(__file__).resolve().parent
    output_dir = Path(args.output_dir).resolve()
    nodes_path = output_dir / "nodes.json"
    report_path = output_dir / "report.md"

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        export_module = _load_module("_clash_export_pipeline", project_dir / "clash_export.py")
        report_module = _load_module(
            "_proxy_report_pipeline", _report_script_path(project_dir)
        )
    except (OSError, ImportError, SyntaxError) as exc:
        return _error("无法加载流水线模块: %s" % exc)

    export_args = [
        "--controller", args.controller,
        "--secret", args.secret,
        "--output", str(nodes_path),
        "--delay-url", args.delay_url,
        "--concurrency", str(args.concurrency),
        "--retry", str(args.retry),
        "--timeout", str(args.timeout),
    ]
    if args.test_delay:
        export_args.append("--test-delay")
    if args.csv:
        export_args += ["--csv", str(output_dir / "nodes.csv")]

    try:
        export_status = export_module.main(export_args)
    except SystemExit as exc:
        export_status = exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:
        return _error("节点导出失败: %s" % exc)
    if export_status != 0:
        return 2

    try:
        with nodes_path.open("r", encoding="utf-8-sig") as source:
            nodes = json.load(source)
        if not isinstance(nodes, list):
            return _error("导出结果不是 JSON 数组")
        total = len(nodes)
        alive = sum(
            1 for node in nodes
            if isinstance(node, dict) and node.get("alive") is True
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _error("无法读取导出结果: %s" % exc)

    try:
        report_status = report_module.main([
            "--input", str(nodes_path),
            "--output", str(report_path),
        ])
    except SystemExit as exc:
        report_status = exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:
        return _error("报告生成失败: %s" % exc)
    if report_status != 0:
        return 2

    print("导出 %d 个节点（存活 %d），报告: %s" % (total, alive, report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
