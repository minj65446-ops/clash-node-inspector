#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按巡检结果裁剪 Clash 配置文件：删掉失效节点，并清理变空的策略组。

设计约束与仓库一致：只用标准库，不做完整 YAML 解析，而是按「顶层分节 + 列表项」
的文本结构做最小外科手术，其余内容逐字节保留（注释、缩进、flow 写法都不动）。
"""
import argparse
import json
import os
import re
import sys
import time

BUILTIN = {"DIRECT", "REJECT", "REJECT-DROP", "GLOBAL", "PASS", "COMPATIBLE"}
SECTION_RE = re.compile(r"^([A-Za-z0-9_-]+):")
NAME_RE = re.compile(
    r"""(?:^|[\s{])name:\s*(?:"([^"]*)"|'([^']*)'|([^,}\n]+))""")
MEMBER_RE = re.compile(r"^(\s+)-\s+(.+?)\s*$")
SUBKEY_RE = re.compile(r"^\s+[A-Za-z0-9_-]+:\s*")


def _unquote(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def split_sections(lines):
    """返回 {分节名: (起始行, 结束行)}，只认列首的分节键。"""
    sections = {}
    current = None
    for index, line in enumerate(lines):
        match = SECTION_RE.match(line)
        if match:
            if current:
                sections[current[0]] = (current[1], index)
            current = (match.group(1), index)
    if current:
        sections[current[0]] = (current[1], len(lines))
    return sections


def list_entries(lines, span):
    """把某一分节内的顶层列表项切成 [(起, 止)] 行区间。"""
    start, end = span
    entries = []
    cursor = None
    for index in range(start, end):
        line = lines[index]
        if line.startswith("- "):
            if cursor is not None:
                entries.append((cursor, index))
            cursor = index
        elif line.strip() and not line.startswith((" ", "\t")) and index != start:
            break
    if cursor is not None:
        entries.append((cursor, end))
    return entries


def entry_name(lines, entry):
    text = "\n".join(lines[entry[0]:entry[1]])
    match = NAME_RE.search(text)
    if not match:
        return None
    return next(group for group in match.groups() if group is not None).strip()


def group_member_lines(lines, entry):
    """返回策略组里 members 列表行号（proxies: 之后的 - xxx 行）。"""
    rows = []
    inside = False
    for index in range(entry[0], entry[1]):
        line = lines[index]
        if re.match(r"^\s+proxies:\s*$", line):
            inside = True
            continue
        if inside:
            if MEMBER_RE.match(line):
                rows.append(index)
            elif SUBKEY_RE.match(line):
                inside = False
    return rows


def prune(profile_text, keep_names, keep_groups=None):
    """裁剪配置文本，返回 (新文本, 统计)。"""
    lines = profile_text.splitlines(keepends=True)
    sections = split_sections(lines)

    stats = {"removed_proxies": [], "removed_groups": [], "removed_members": 0}
    drop_lines = set()

    group_names = set(keep_groups or [])
    group_entries = []
    if "proxy-groups" in sections:
        group_entries = list_entries(lines, sections["proxy-groups"])
        for entry in group_entries:
            name = entry_name(lines, entry)
            if name:
                group_names.add(name)

    if "proxies" in sections:
        for entry in list_entries(lines, sections["proxies"]):
            name = entry_name(lines, entry)
            if name is None or name in BUILTIN or name in keep_names:
                continue
            stats["removed_proxies"].append(name)
            drop_lines.update(range(entry[0], entry[1]))

    # 反复收敛：成员全被删掉的组也要删，删组后又可能有组变空。
    alive_groups = set(group_names)
    changed = True
    while changed:
        changed = False
        for entry in group_entries:
            name = entry_name(lines, entry)
            if not name or name not in alive_groups:
                continue
            members = [
                _unquote(MEMBER_RE.match(lines[row]).group(2))
                for row in group_member_lines(lines, entry)
            ]
            if not members:
                continue
            if not any(m in keep_names or m in alive_groups or m in BUILTIN
                       for m in members):
                alive_groups.discard(name)
                stats["removed_groups"].append(name)
                changed = True

    for entry in group_entries:
        name = entry_name(lines, entry)
        if name and name not in alive_groups:
            drop_lines.update(range(entry[0], entry[1]))
            continue
        for row in group_member_lines(lines, entry):
            member = _unquote(MEMBER_RE.match(lines[row]).group(2))
            if member in keep_names or member in alive_groups or member in BUILTIN:
                continue
            drop_lines.add(row)
            stats["removed_members"] += 1

    result = "".join(
        line for index, line in enumerate(lines) if index not in drop_lines
    )
    return result, stats


def load_keep_names(node_file, include_dead):
    with open(node_file, "r", encoding="utf-8-sig") as source:
        data = json.load(source)
    if not isinstance(data, list):
        raise ValueError("节点 JSON 顶层必须是数组")
    names = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        if include_dead or item.get("alive") is True:
            names.append(item["name"])
    return names


def main(argv=None):
    parser = argparse.ArgumentParser(description="按巡检结果裁剪 Clash 配置")
    parser.add_argument("--profile", required=True, help="原始 Clash / mihomo 配置文件")
    parser.add_argument("--nodes", required=True, help="clash_export 输出的节点 JSON")
    parser.add_argument("--out", default=None, help="输出路径（默认 <profile>.pruned.yaml）")
    parser.add_argument("--in-place", action="store_true", help="直接覆盖原文件（自动备份）")
    parser.add_argument("--include-dead", action="store_true", help="保留未测速/不可用节点")
    parser.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    args = parser.parse_args(argv)

    try:
        keep_names = set(load_keep_names(args.nodes, args.include_dead))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("错误：无法读取节点 JSON: %s" % exc, file=sys.stderr)
        return 2
    if not keep_names:
        print("错误：节点 JSON 里没有可保留的节点，拒绝裁剪", file=sys.stderr)
        return 2

    try:
        with open(args.profile, "r", encoding="utf-8") as source:
            original = source.read()
    except OSError as exc:
        print("错误：无法读取配置: %s" % exc, file=sys.stderr)
        return 2

    result, stats = prune(original, keep_names)
    print(
        "裁剪结果：删除节点 %d，删除策略组 %d，清理成员引用 %d"
        % (len(stats["removed_proxies"]), len(stats["removed_groups"]),
           stats["removed_members"])
    )
    for name in stats["removed_proxies"]:
        print("  - 节点 %s" % name)
    for name in stats["removed_groups"]:
        print("  - 策略组 %s" % name)

    if args.dry_run:
        return 0

    target = args.profile if args.in_place else (args.out or args.profile + ".pruned.yaml")
    if args.in_place:
        backup = "%s.bak-%s" % (args.profile, time.strftime("%Y%m%d-%H%M%S"))
        try:
            with open(backup, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(original)
        except OSError as exc:
            print("错误：备份失败: %s" % exc, file=sys.stderr)
            return 2
        print("已备份到 %s" % backup)

    try:
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(result)
    except OSError as exc:
        print("错误：写入失败: %s" % exc, file=sys.stderr)
        return 2
    print("已写入 %s" % target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
