#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日巡检：运行 pipeline（导出+报告+CSV），归档并按日期维护趋势。

用法：
    python daily_inspect.py [--secret TOKEN] [--threshold 60] [--no-delay]

密钥优先级：--secret > 环境变量 CLASH_SECRET > 本目录 .clash_secret 文件。
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(HERE, "pipeline.py")
if not os.path.isfile(PIPELINE):
    PIPELINE = os.path.join(HERE, "clash_export", "pipeline.py")
REPORTS = os.path.join(HERE, "reports")
SECRET_FILE = os.path.join(HERE, ".clash_secret")


def resolve_secret(cli_value):
    if cli_value:
        return cli_value
    env = os.environ.get("CLASH_SECRET", "")
    if env:
        return env
    if os.path.isfile(SECRET_FILE):
        with open(SECRET_FILE, encoding="utf-8") as f:
            return f.read().strip()
    return ""


def run_pipeline(secret, out_dir, concurrency, retry, timeout, no_delay):
    cmd = [
        sys.executable, PIPELINE,
        "--secret", secret,
        "--output-dir", out_dir,
        "--csv",
    ]
    if not no_delay:
        cmd += ["--test-delay", "--concurrency", str(concurrency),
                "--retry", str(retry), "--timeout", str(timeout)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=900, env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "pipeline 失败").strip())
    return (proc.stdout or "").strip()


def stats_of(nodes):
    total = len(nodes)
    alive_nodes = [n for n in nodes if n.get("alive") is True]
    delays = [n["delay_ms"] for n in alive_nodes if isinstance(n.get("delay_ms"), int)]
    delays.sort()
    if not delays:
        median = None
    elif len(delays) % 2:
        median = delays[len(delays) // 2]
    else:
        pair = delays[len(delays) // 2 - 1] + delays[len(delays) // 2]
        median = int(pair / 2.0 + 0.5)
    rate = round(len(alive_nodes) * 100.0 / total, 1) if total else 0.0
    regions = {}
    for n in nodes:
        regions.setdefault(n.get("region") or "UNKNOWN", [0, 0])
        regions[n.get("region") or "UNKNOWN"][0] += 1
        if n.get("alive") is True:
            regions[n.get("region") or "UNKNOWN"][1] += 1
    return {"total": total, "alive": len(alive_nodes), "rate": rate,
            "median": median, "regions": regions}


def load_history(path):
    items = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if "date" in entry:
                    items[entry["date"]] = entry
    return items


def save_history(path, items):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for date in sorted(items):
            f.write(json.dumps(items[date], ensure_ascii=False) + "\n")


def render_index(items, threshold):
    lines = [
        "# Clash 节点质量趋势",
        "",
        "| 日期 | 节点数 | 存活 | 存活率 | 中位延迟 | 状态 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for date in sorted(items, reverse=True)[:30]:
        e = items[date]
        status = "✅" if e["rate"] >= threshold else "⚠️"
        median = "-" if e["median"] is None else "%d ms" % e["median"]
        lines.append("| %s | %d | %d | %.1f%% | %s | %s |"
                     % (date, e["total"], e["alive"], e["rate"], median, status))
    lines += ["", "> 状态阈值：存活率 ≥ %.1f%% 为 ✅，否则 ⚠️" % threshold]
    return "\n".join(lines) + "\n"


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Clash 节点每日巡检")
    parser.add_argument("--secret", default="")
    parser.add_argument("--controller", default="http://127.0.0.1:9097")
    parser.add_argument("--reports-root", default=REPORTS)
    parser.add_argument("--threshold", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--retry", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=2500)
    parser.add_argument("--no-delay", action="store_true")
    args = parser.parse_args(argv)

    secret = resolve_secret(args.secret)
    if not secret:
        print("错误：未提供 --secret / CLASH_SECRET / .clash_secret", file=sys.stderr)
        return 2

    date = time.strftime("%Y-%m-%d")
    out_dir = os.path.join(args.reports_root, date)
    os.makedirs(out_dir, exist_ok=True)

    try:
        summary = run_pipeline(secret, out_dir, args.concurrency, args.retry,
                               args.timeout, args.no_delay)
    except Exception as exc:
        print("巡检失败: %s" % exc, file=sys.stderr)
        return 2

    with open(os.path.join(out_dir, "nodes.json"), encoding="utf-8") as f:
        nodes = json.load(f)
    st = stats_of(nodes)

    history_path = os.path.join(args.reports_root, "history.jsonl")
    items = load_history(history_path)
    items[date] = {"date": date, "total": st["total"], "alive": st["alive"],
                   "rate": st["rate"], "median": st["median"],
                   "regions": st["regions"]}
    save_history(history_path, items)
    with open(os.path.join(args.reports_root, "index.md"), "w", encoding="utf-8") as f:
        f.write(render_index(items, args.threshold))

    print("巡检完成: %s" % date)
    print("  %s" % summary)
    print("  节点 %d / 存活 %d (%.1f%%) / 中位延迟 %s"
          % (st["total"], st["alive"], st["rate"],
             "-" if st["median"] is None else "%d ms" % st["median"]))
    print("  报告: %s" % os.path.join(out_dir, "report.md"))
    print("  趋势: %s" % os.path.join(args.reports_root, "index.md"))
    if st["rate"] < args.threshold:
        print("⚠ 存活率低于阈值 %.1f%%，建议检查节点订阅" % args.threshold)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
