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
    parser.add_argument("--dedupe", action="store_true", help="按名称后缀归并重复节点")
    parser.add_argument("--profile", default=None,
                        help="配合 --dedupe：从该配置读 server:port 按真实出口去重"
                             "（默认复用 --prune-profile）")
    parser.add_argument("--keep-region", default="", help="只保留这些地区，逗号分隔")
    parser.add_argument("--exclude-region", default="", help="排除这些地区，逗号分隔")
    parser.add_argument("--max-delay", type=int, default=None, help="延迟上限（ms）")
    parser.add_argument("--only-alive", action="store_true", help="只保留测速成功的节点")
    parser.add_argument("--prune-profile", default=None,
                        help="按巡检结果裁剪该 Clash 配置文件")
    parser.add_argument("--prune-out", default=None,
                        help="裁剪结果输出路径（默认 <profile>.pruned.yaml）")
    parser.add_argument("--prune-in-place", action="store_true",
                        help="直接覆盖 --prune-profile 指定的文件（自动备份）")
    args = parser.parse_args(argv)
    if args.prune_in_place and not args.prune_profile:
        parser.error("--prune-in-place 需要同时指定 --prune-profile")

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
    if args.dedupe:
        export_args.append("--dedupe")
        identity_source = args.profile or args.prune_profile
        if identity_source:
            export_args += ["--profile", identity_source]
    if args.keep_region:
        export_args += ["--keep-region", args.keep_region]
    if args.exclude_region:
        export_args += ["--exclude-region", args.exclude_region]
    if args.max_delay is not None:
        export_args += ["--max-delay", str(args.max_delay)]
    if args.only_alive:
        export_args.append("--only-alive")

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

    if args.prune_profile:
        try:
            prune_module = _load_module(
                "_clash_prune_pipeline", project_dir / "clash_prune.py"
            )
        except (OSError, ImportError, SyntaxError) as exc:
            return _error("无法加载裁剪模块: %s" % exc)
        prune_args = [
            "--profile", args.prune_profile,
            "--nodes", str(nodes_path),
        ]
        if args.prune_in_place:
            prune_args.append("--in-place")
        elif args.prune_out:
            prune_args += ["--out", args.prune_out]
        try:
            prune_status = prune_module.main(prune_args)
        except SystemExit as exc:
            prune_status = exc.code if isinstance(exc.code, int) else 2
        if prune_status != 0:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
