#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Clash 配置文本里读出「节点名 → 真实出口标识（server:port）」。

Clash 控制器不返回 server/port，所以只靠 API 无法判断
`NL_speednode_0004` 与 `NL_speednode_0005` 是不是同一台机器。
这个模块做文本级解析（只用标准库，不引入 YAML 依赖），补上这块信息。

为了每个脚本都能独立运行，这里的分节/列表项切分逻辑与 clash_prune.py 各自
保留一份，两者都只依赖标准库，改动时请保持同步。
"""
import re
import sys

SECTION_RE = re.compile(r"^([A-Za-z0-9_-]+):")
NAME_RE = re.compile(
    r"""(?:^|[\s{])name:\s*(?:"([^"]*)"|'([^']*)'|([^,}\n]+))""")
FIELD_RE = r"""(?:^|[\s{{]){key}:\s*(?:"([^"]*)"|'([^']*)'|([^,}}\n]+))"""


def unquote(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _field(entry_text, key):
    match = re.search(FIELD_RE.format(key=key), entry_text, re.M)
    if not match:
        return None
    return next(group for group in match.groups() if group is not None).strip()


def split_sections(lines):
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


def parse_proxies(text):
    """返回 [{"name", "server", "port", "type"}]，缺字段的项原样留空。"""
    lines = text.splitlines(keepends=True)
    sections = split_sections(lines)
    if "proxies" not in sections:
        return []
    result = []
    for entry in list_entries(lines, sections["proxies"]):
        entry_text = "".join(lines[entry[0]:entry[1]])
        match = NAME_RE.search(entry_text)
        if not match:
            continue
        name = next(g for g in match.groups() if g is not None).strip()
        port = _field(entry_text, "port")
        result.append(
            {
                "name": name,
                "server": _field(entry_text, "server"),
                "port": int(port) if port and port.isdigit() else None,
                "type": _field(entry_text, "type"),
            }
        )
    return result


def identity_map(text):
    """节点名 → "server:port"；缺 server/port 的节点不收录。"""
    mapping = {}
    for item in parse_proxies(text):
        if item["server"] and item["port"]:
            mapping[item["name"]] = "%s:%s" % (item["server"], item["port"])
    return mapping


def identity_map_from_file(path):
    with open(path, "r", encoding="utf-8-sig") as source:
        return identity_map(source.read())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python clash_profile.py <profile.yaml>", file=sys.stderr)
        raise SystemExit(2)
    for name, ident in sorted(identity_map_from_file(sys.argv[1]).items()):
        print("%s\t%s" % (ident, name))
