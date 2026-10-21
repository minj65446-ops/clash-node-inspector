#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参考实现 v2（仅用于验证验收测试本身，不放进交接项目目录）。"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

SKIP_TYPES = {
    "selector", "urltest", "fallback", "loadbalance", "relay", "direct",
    "reject", "rejectdrop", "pass", "passrule", "compatible", "dns",
}
SKIP_NAMES = {"direct", "reject", "reject-drop", "global", "compatible", "pass", "pass-rule"}

# (代码, 中文关键字, 英文关键字, 代码 token)
REGIONS = [
    ("HK", ["香港"], ["hong kong"], ["hk", "hkg"]),
    ("SG", ["新加坡"], ["singapore"], ["sg", "sin"]),
    ("JP", ["日本", "东京", "大阪"], ["japan", "tokyo", "osaka"], ["jp", "nrt", "hnd", "tyo"]),
    ("TW", ["台湾", "台北"], ["taiwan", "taipei"], ["tw", "tpe"]),
    ("KR", ["韩国", "首尔"], ["korea", "seoul"], ["kr", "icn"]),
    ("US", ["美国"], ["united states", "america"], ["us", "lax", "sfo", "jfk", "sea"]),
    ("NL", ["荷兰"], ["netherlands", "holland"], ["nl", "ams"]),
    ("RO", ["罗马尼亚"], ["romania"], ["ro", "otp"]),
    ("DE", ["德国"], ["germany"], ["de", "fra"]),
    ("GB", ["英国"], ["united kingdom", "england", "britain"], ["gb", "uk", "lhr"]),
    ("FR", ["法国"], ["france"], ["fr", "cdg"]),
    ("CA", ["加拿大"], ["canada"], ["ca", "yyz"]),
    ("AU", ["澳大利亚"], ["australia"], ["au", "syd"]),
    ("RU", ["俄罗斯"], ["russia"], ["ru", "svo"]),
    ("TR", ["土耳其"], ["turkey"], ["tr", "ist"]),
    ("IN", ["印度"], ["india"], ["in", "bom"]),
    ("TH", ["泰国"], ["thailand"], ["th", "bkk"]),
    ("VN", ["越南"], ["vietnam"], ["vn", "sgn"]),
    ("MY", ["马来西亚"], ["malaysia"], ["my", "kul"]),
    ("BR", ["巴西"], ["brazil"], ["br", "gru"]),
    ("PL", ["波兰"], ["poland"], ["pl", "waw"]),
    ("SE", ["瑞典"], ["sweden"], ["se", "arn"]),
    ("FI", ["芬兰"], ["finland"], ["fi", "hel"]),
    ("CH", ["瑞士"], ["switzerland"], ["ch", "zrh"]),
    ("ES", ["西班牙"], ["spain"], ["es", "mad"]),
    ("IT", ["意大利"], ["italy"], ["it", "fco"]),
    ("IE", ["爱尔兰"], ["ireland"], ["ie", "dub"]),
    ("AE", ["阿联酋", "迪拜"], ["emirates", "dubai"], ["ae", "dxb"]),
]
TOKEN_RE = re.compile(r"[0-9a-z]+|[\u4e00-\u9fff]+")


class AuthError(Exception):
    pass


def infer_region(name):
    lowered = name.lower()
    tokens = set(TOKEN_RE.findall(lowered))
    compact = lowered.replace(" ", "")
    for code, cjk_keywords, en_keywords, code_tokens in REGIONS:
        if any(k in lowered for k in cjk_keywords):
            return code
        if any(k.replace(" ", "") in compact for k in en_keywords):
            return code
        if any(t in tokens for t in code_tokens):
            return code
    return "UNKNOWN"


def http_get(url, secret, timeout=15):
    headers = {}
    if secret:
        headers["Authorization"] = "Bearer " + secret
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""


def fail(message):
    print("错误：" + str(message), file=sys.stderr)
    return 2


def test_delay(base, secret, name, delay_url, timeout_ms):
    url = "%s/proxies/%s/delay?url=%s&timeout=%d" % (
        base,
        urllib.parse.quote(name, safe=""),
        urllib.parse.quote(delay_url, safe=""),
        timeout_ms,
    )
    status, body = http_get(url, secret, timeout=max(timeout_ms, 1) / 1000.0)
    if status == 401:
        raise AuthError("延迟测试时认证失败（HTTP 401）")
    if status != 200:
        return False, None
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False, None
    delay = data.get("delay") if isinstance(data, dict) else None
    if isinstance(delay, int) and not isinstance(delay, bool) and delay > 0:
        return True, delay
    return False, None



SUFFIX_RE = re.compile(r"\s*(\(\d+\)|#\d+|-\d+)\s*$")


def name_fingerprint(name):
    """同一节点的不同副本（如 "X (2)" / "X #2"）归一到同一个指纹。

    注意：Clash 控制器不返回 server/port，因此无法按真实地址去重，
    只能按名称后缀做启发式归并。
    """
    return SUFFIX_RE.sub("", name.strip()).casefold()


def dedupe_nodes(nodes):
    """按名称指纹去重，保留"没有后缀且延迟最低"的代表，返回 (保留, 剔除)。"""
    groups = {}
    order = []
    for node in nodes:
        key = name_fingerprint(node["name"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(node)

    kept, dropped = [], []
    for key in order:
        candidates = groups[key]
        if len(candidates) == 1:
            kept.append(candidates[0])
            continue

        def rank(node):
            has_suffix = bool(SUFFIX_RE.search(node["name"].strip()))
            delay = node["delay_ms"] if isinstance(node["delay_ms"], int) else 10 ** 9
            return (has_suffix, delay, node["name"])

        candidates = sorted(candidates, key=rank)
        kept.append(candidates[0])
        dropped.extend(candidates[1:])
    kept.sort(key=lambda n: n["name"])
    return kept, dropped


def parse_region_set(text):
    return {item.strip().upper() for item in (text or "").split(",") if item.strip()}


def apply_filters(nodes, keep_regions=None, exclude_regions=None,
                  max_delay=None, only_alive=False):
    """按地区白/黑名单、延迟上限、存活状态过滤，返回 (保留, 剔除列表[(node, 原因)])。"""
    kept, dropped = [], []
    for node in nodes:
        reason = None
        if keep_regions and node["region"] not in keep_regions:
            reason = "地区不在白名单"
        elif exclude_regions and node["region"] in exclude_regions:
            reason = "地区被排除"
        elif not node["alive"]:
            if max_delay is not None or only_alive:
                reason = "不可用"
        elif max_delay is not None and (node["delay_ms"] or 0) > max_delay:
            reason = "延迟超过 %d ms" % max_delay
        if reason:
            dropped.append((node, reason))
        else:
            kept.append(node)
    return kept, dropped


def write_csv(nodes, path):
    """把节点列表写成 CSV（name,region,delay_ms,alive）。"""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "region", "delay_ms", "alive"])
        writer.writeheader()
        for node in nodes:
            writer.writerow({
                "name": node["name"],
                "region": node["region"],
                "delay_ms": "" if node["delay_ms"] is None else node["delay_ms"],
                "alive": "true" if node["alive"] else "false",
            })


def main(argv=None):
    parser = argparse.ArgumentParser(description="从 Clash 控制器导出节点 JSON")
    parser.add_argument("--controller", default="http://127.0.0.1:9097")
    parser.add_argument("--secret", default=os.environ.get("CLASH_SECRET", ""))
    parser.add_argument("--output", default=None)
    parser.add_argument("--csv", default=None, help="额外输出 CSV 文件路径")
    parser.add_argument("--test-delay", action="store_true")
    parser.add_argument("--delay-url", default="http://www.gstatic.com/generate_204")
    parser.add_argument("--timeout", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--retry", type=int, default=0)
    parser.add_argument("--dedupe", action="store_true",
                        help="按名称后缀归并重复节点（如 X 与 X (2)），保留延迟最低者")
    parser.add_argument("--keep-region", default="",
                        help="只保留这些地区，逗号分隔，如 HK,JP,SG")
    parser.add_argument("--exclude-region", default="",
                        help="排除这些地区，逗号分隔，如 RU,CN")
    parser.add_argument("--max-delay", type=int, default=None,
                        help="延迟上限（ms）；会同时剔除不可用节点")
    parser.add_argument("--only-alive", action="store_true", help="只保留测速成功的节点")
    parser.add_argument("--stats", action="store_true", help="把过滤统计输出到 stderr")
    args = parser.parse_args(argv)

    if not 1 <= args.concurrency <= 16:
        parser.error("--concurrency 必须在 1..16 之间")
    if not 0 <= args.retry <= 5:
        parser.error("--retry 必须在 0..5 之间")

    base = args.controller.rstrip("/")
    status, body = http_get(base + "/proxies", args.secret)
    if status != 200:
        return fail("控制器请求失败: HTTP %s" % status)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return fail("控制器响应不是合法 JSON: %s" % exc)
    if not isinstance(payload, dict) or not isinstance(payload.get("proxies"), dict):
        return fail("/proxies 响应结构不正确")

    nodes = []
    for name, info in payload["proxies"].items():
        if not name or not isinstance(info, dict):
            continue
        if name.lower() in SKIP_NAMES:
            continue
        if str(info.get("type", "")).lower() in SKIP_TYPES:
            continue
        nodes.append({"name": name, "region": infer_region(name), "delay_ms": None, "alive": False})
    nodes.sort(key=lambda n: n["name"])

    raw_total = len(nodes)
    if args.dedupe:
        nodes, deduped = dedupe_nodes(nodes)
    else:
        deduped = []

    if args.test_delay:
        def test_delay_with_retry(name):
            # Authentication errors propagate immediately and are never retried.
            for attempt in range(args.retry + 1):
                alive, delay = test_delay(
                    base, args.secret, name, args.delay_url, args.timeout)
                if alive or attempt == args.retry:
                    return alive, delay
            return False, None

        try:
            if args.concurrency == 1:
                for node in nodes:
                    node["alive"], node["delay_ms"] = test_delay_with_retry(node["name"])
            else:
                with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                    futures = {
                        pool.submit(test_delay_with_retry, node["name"]): node
                        for node in nodes
                    }
                    for future in as_completed(futures):
                        try:
                            futures[future]["alive"], futures[future]["delay_ms"] = future.result()
                        except AuthError:
                            for pending in futures:
                                pending.cancel()
                            raise
        except AuthError:
            return fail("延迟测试时认证失败（HTTP 401），请检查 --secret")

    nodes, filtered = apply_filters(
        nodes,
        keep_regions=parse_region_set(args.keep_region),
        exclude_regions=parse_region_set(args.exclude_region),
        max_delay=args.max_delay,
        only_alive=args.only_alive,
    )

    if args.stats:
        no_delay = sum(1 for n in nodes if not n["alive"])
        print(
            "过滤统计：原始 %d → 保留 %d（去重 %d，策略剔除 %d，其中不可用 %d）"
            % (raw_total, len(nodes), len(deduped), len(filtered), no_delay),
            file=sys.stderr,
        )
        for node, reason in filtered:
            print("  剔除 %s（%s）" % (node["name"], reason), file=sys.stderr)

    if args.csv:
        try:
            write_csv(nodes, args.csv)
        except OSError as exc:
            return fail("无法写入 CSV 文件: %s" % exc)

    text = json.dumps(nodes, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except OSError as exc:
            return fail("无法写入输出文件: %s" % exc)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

