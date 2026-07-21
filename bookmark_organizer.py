#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bookmark_organizer.py

Reorganize Chrome / Edge Netscape Bookmark HTML exports with an external JSON
policy. Folder taxonomy, priority order, and classification rules live in
bookmark_policy.json instead of being hardcoded in Python.

Examples:
    python3 bookmark_organizer.py bookmarks.html -o bookmarks_organized.html
    python3 bookmark_organizer.py bookmarks.html --policy bookmark_policy.json \
        -o bookmarks_organized.html --report organizer_report.json
    python3 bookmark_organizer.py bookmarks.html --dry-run

Behavior:
- Reclassifies every bookmark through policy rules.
- Removes duplicate normalized URLs, preferring 01_常用 when duplicated.
- Preserves bookmark titles, URLs, timestamps, icons, and other attributes.
- Keeps configured top-level system folders even when empty.
- Numbers every nested folder as 01_, 02_, ... according to policy priority.
- Unknown bookmarks fall back to 00_待整理 instead of guessing.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

NUMBER_PREFIX_RE = re.compile(r"^(\d{2})_(.+)$")
TRACKING_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "fbclid", "gclid", "yclid", "mc_cid", "mc_eid",
}


class NetscapeBookmarkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = {"type": "folder", "title": "ROOT", "attrs": {}, "children": []}
        self.stack = [self.root]
        self.capture: Optional[str] = None
        self.text_buf: list[str] = []
        self.attrs_buf: dict[str, str] = {}
        self.pending_folder: Optional[dict] = None
        self.outer_dl_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag == "h3":
            self.capture = "h3"
            self.text_buf = []
            self.attrs_buf = attr_map
        elif tag == "a":
            self.capture = "a"
            self.text_buf = []
            self.attrs_buf = attr_map
        elif tag == "dl":
            if self.pending_folder is not None:
                self.stack[-1]["children"].append(self.pending_folder)
                self.stack.append(self.pending_folder)
                self.pending_folder = None
            else:
                self.outer_dl_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "h3" and self.capture == "h3":
            self.pending_folder = {
                "type": "folder",
                "title": "".join(self.text_buf).strip(),
                "attrs": dict(self.attrs_buf),
                "children": [],
            }
            self.capture = None
            self.text_buf = []
        elif tag == "a" and self.capture == "a":
            self.stack[-1]["children"].append({
                "type": "link",
                "title": "".join(self.text_buf).strip(),
                "href": self.attrs_buf.get("href", ""),
                "attrs": dict(self.attrs_buf),
            })
            self.capture = None
            self.text_buf = []
        elif tag == "dl":
            if len(self.stack) > 1:
                self.stack.pop()
            elif self.outer_dl_depth:
                self.outer_dl_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.text_buf.append(data)


def parse_bookmark_file(path: Path) -> dict:
    parser = NetscapeBookmarkParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser.root


def find_toolbar_root(root: dict) -> dict:
    folders = [child for child in root["children"] if child["type"] == "folder"]
    if not folders:
        return root
    preferred = [f for f in folders if f["attrs"].get("personal_toolbar_folder") == "true"]
    if preferred:
        return preferred[0]
    named = [f for f in folders if f["title"] in {"书签栏", "收藏夹栏", "Bookmarks bar"}]
    return named[0] if named else folders[0]


def strip_number_prefix(name: str) -> str:
    match = NUMBER_PREFIX_RE.match(name)
    return match.group(2) if match else name


def canonical_path(path: tuple[str, ...], top_level_order: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    for index, name in enumerate(path):
        if index == 0 and name in top_level_order:
            result.append(name)
        else:
            result.append(strip_number_prefix(name))
    return tuple(result)


def walk_links(node: dict, path: tuple[str, ...] = ()):  # yields dict records
    for child in node["children"]:
        if child["type"] == "folder":
            yield from walk_links(child, path + (child["title"],))
        else:
            yield {
                "title": child["title"],
                "href": child.get("href", ""),
                "attrs": deepcopy(child.get("attrs", {})),
                "old_path": path,
            }


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    path = parts.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [
        (k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_KEYS and not k.lower().startswith("utm_")
    ]
    query = urllib.parse.urlencode(query_pairs, doseq=True)
    fragment = "" if parts.fragment.startswith(":~:text=") else parts.fragment
    return urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))


def path_startswith(path: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return len(path) >= len(prefix) and path[:len(prefix)] == prefix


def matches_title_rule(record: dict, rule: dict) -> bool:
    title = record["title"].casefold()
    href = record["href"].casefold()
    text = f"{title}\n{href}"

    old_prefix = tuple(rule.get("old_path_prefix", []))
    if old_prefix and not path_startswith(record["canonical_old_path"], old_prefix):
        return False

    any_terms = [str(x).casefold() for x in rule.get("contains_any", [])]
    all_terms = [str(x).casefold() for x in rule.get("contains_all", [])]
    none_terms = [str(x).casefold() for x in rule.get("contains_none", [])]

    if any_terms and not any(term in text for term in any_terms):
        return False
    if all_terms and not all(term in text for term in all_terms):
        return False
    if none_terms and any(term in text for term in none_terms):
        return False
    return bool(any_terms or all_terms or old_prefix)


def classify_record(record: dict, policy: dict) -> tuple[tuple[str, ...], str]:
    classification = policy.get("classification", {})
    normalized = normalize_url(record["href"])

    exact_map = {
        normalize_url(url): tuple(path)
        for url, path in classification.get("exact_url_overrides", {}).items()
    }
    if normalized in exact_map:
        return exact_map[normalized], "exact_url_override"

    for rule in classification.get("title_rules", []):
        if matches_title_rule(record, rule):
            return tuple(rule["path"]), "title_rule"

    old_path = record["canonical_old_path"]
    fallback_map = {
        tuple(key.split(" / ")): tuple(value)
        for key, value in classification.get("fallback_path_map", {}).items()
    }
    matches = [prefix for prefix in fallback_map if path_startswith(old_path, prefix)]
    if matches:
        prefix = max(matches, key=len)
        target = fallback_map[prefix]
        remainder = old_path[len(prefix):]
        return target + remainder, "fallback_path"

    return ("00_待整理",), "unclassified"


def choose_duplicate(candidates: list[dict]) -> dict:
    def score(record: dict) -> tuple[int, int, int]:
        path = record["new_path"]
        top = path[0] if path else ""
        value = 0
        if top == "01_常用":
            value += 1000
        if top != "00_待整理":
            value += 200
        if top != "90_历史归档":
            value += 50
        value += min(len(path), 9)
        return value, len(record["title"]), -record["source_index"]
    return max(candidates, key=score)


def make_folder(title: str) -> dict:
    return {"type": "folder", "title": title, "attrs": {}, "children": []}


def build_tree(records: list[dict], policy: dict) -> dict:
    toolbar = make_folder("书签栏")
    toolbar["attrs"]["personal_toolbar_folder"] = "true"
    folder_cache: dict[tuple[str, ...], dict] = {(): toolbar}

    for top in policy["top_level_order"]:
        folder = make_folder(top)
        toolbar["children"].append(folder)
        folder_cache[(top,)] = folder

    for record in records:
        path = tuple(record["new_path"])
        current_path: tuple[str, ...] = ()
        current = toolbar
        for folder_name in path:
            current_path += (folder_name,)
            if current_path not in folder_cache:
                folder = make_folder(folder_name)
                current["children"].append(folder)
                folder_cache[current_path] = folder
            current = folder_cache[current_path]
        current["children"].append({
            "type": "link",
            "title": record["title"],
            "href": record["href"],
            "attrs": deepcopy(record["attrs"]),
        })

    return toolbar


def number_nested_folders(toolbar: dict, policy: dict) -> int:
    child_order = policy.get("child_order", {})
    changed = 0

    def recurse(node: dict, canonical_parent: tuple[str, ...]) -> None:
        nonlocal changed
        folders = [child for child in node["children"] if child["type"] == "folder"]
        links = [child for child in node["children"] if child["type"] == "link"]

        parent_key = " / ".join(canonical_parent)
        preferred = child_order.get(parent_key, [])
        rank = {name: index for index, name in enumerate(preferred)}
        original_index = {id(folder): index for index, folder in enumerate(folders)}
        folders.sort(key=lambda f: (rank.get(strip_number_prefix(f["title"]), 9999), original_index[id(f)]))

        is_toolbar = not canonical_parent
        for index, folder in enumerate(folders, start=1):
            base = strip_number_prefix(folder["title"])
            if is_toolbar:
                new_title = folder["title"]
                next_canonical = canonical_parent + (folder["title"],)
            else:
                new_title = f"{index:02d}_{base}"
                next_canonical = canonical_parent + (base,)
            if folder["title"] != new_title:
                folder["title"] = new_title
                changed += 1
            recurse(folder, next_canonical)

        node["children"] = folders + links

    recurse(toolbar, ())
    return changed


def attr_text(attrs: dict[str, str], href: Optional[str] = None) -> str:
    values = dict(attrs)
    if href is not None:
        values["href"] = href
    preferred = ["href", "add_date", "last_modified", "icon", "shortcuturl", "tags"]
    keys = [key for key in preferred if key in values]
    keys.extend(key for key in values if key not in keys)
    return " ".join(
        f'{key.upper()}="{html.escape(str(values[key]), quote=True)}"'
        for key in keys if values[key] is not None
    )


def render_netscape(toolbar: dict) -> str:
    now = str(int(time.time()))
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- Reorganized with bookmark_organizer.py using external bookmark_policy.json. -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
        f'    <DT><H3 ADD_DATE="{now}" LAST_MODIFIED="{now}" PERSONAL_TOOLBAR_FOLDER="true">书签栏</H3>',
        "    <DL><p>",
    ]

    def emit(node: dict, level: int) -> None:
        indent = "    " * level
        for child in node["children"]:
            if child["type"] == "folder":
                attrs = dict(child.get("attrs", {}))
                attrs.setdefault("add_date", now)
                attrs.setdefault("last_modified", now)
                lines.append(f'{indent}<DT><H3 {attr_text(attrs)}>{html.escape(child["title"])}</H3>')
                lines.append(f"{indent}<DL><p>")
                emit(child, level + 1)
                lines.append(f"{indent}</DL><p>")
            else:
                attrs = dict(child.get("attrs", {}))
                lines.append(f'{indent}<DT><A {attr_text(attrs, child.get("href", ""))}>{html.escape(child["title"])}</A>')

    emit(toolbar, 2)
    lines.extend(["    </DL><p>", "</DL><p>"])
    return "\n".join(lines) + "\n"


def organize(source: Path, policy_path: Path) -> tuple[dict, dict]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    root = parse_bookmark_file(source)
    toolbar = find_toolbar_root(root)
    top_level_order = policy["top_level_order"]

    records = []
    for index, record in enumerate(walk_links(toolbar)):
        record["source_index"] = index
        record["canonical_old_path"] = canonical_path(tuple(record["old_path"]), top_level_order)
        new_path, method = classify_record(record, policy)
        record["new_path"] = new_path
        record["classification_method"] = method
        records.append(record)

    duplicate_groups = defaultdict(list)
    for record in records:
        duplicate_groups[normalize_url(record["href"])].append(record)

    selected: list[dict] = []
    removed_duplicates: list[dict] = []
    for candidates in duplicate_groups.values():
        chosen = choose_duplicate(candidates)
        selected.append(chosen)
        removed_duplicates.extend(item for item in candidates if item is not chosen)
    selected.sort(key=lambda r: r["source_index"])

    output_toolbar = build_tree(selected, policy)
    numbered_folders = number_nested_folders(output_toolbar, policy)

    method_counts = Counter(record["classification_method"] for record in selected)
    old_pending = sum(1 for r in records if r["canonical_old_path"] and r["canonical_old_path"][0] == "00_待整理")
    new_pending = sum(1 for r in selected if r["new_path"] and r["new_path"][0] == "00_待整理")
    path_moves = sum(1 for r in selected if tuple(r["canonical_old_path"]) != tuple(r["new_path"]))
    top_moves = sum(
        1 for r in selected
        if r["canonical_old_path"] and r["new_path"]
        and r["canonical_old_path"][0] != r["new_path"][0]
    )
    top_counts = Counter(r["new_path"][0] for r in selected)

    report = {
        "source": str(source),
        "policy": str(policy_path),
        "policy_version": policy.get("version"),
        "input_bookmarks": len(records),
        "output_bookmarks": len(selected),
        "duplicates_removed": len(removed_duplicates),
        "old_pending": old_pending,
        "new_pending": new_pending,
        "path_moves": path_moves,
        "top_level_moves": top_moves,
        "numbered_or_renumbered_folders": numbered_folders,
        "classification_methods": dict(method_counts),
        "top_level_counts": dict(top_counts),
        "removed_duplicates": [
            {
                "title": r["title"],
                "old_path": list(r["canonical_old_path"]),
                "new_path": list(r["new_path"]),
                "normalized_url": normalize_url(r["href"]),
            }
            for r in removed_duplicates
        ],
        "moves": [
            {
                "title": r["title"],
                "old_path": list(r["canonical_old_path"]),
                "new_path": list(r["new_path"]),
                "method": r["classification_method"],
            }
            for r in selected if tuple(r["canonical_old_path"]) != tuple(r["new_path"])
        ],
    }
    return output_toolbar, report


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reorganize bookmark HTML using an external JSON policy.")
    parser.add_argument("source", type=Path, help="Chrome/Edge Netscape bookmark HTML export")
    parser.add_argument("-o", "--output", type=Path, help="Output HTML path")
    parser.add_argument("--policy", type=Path, default=Path("bookmark_policy.json"), help="Policy JSON path")
    parser.add_argument("--report", type=Path, help="Write JSON organizer report")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only; do not write HTML")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if not args.source.exists():
        print(f"ERROR: source not found: {args.source}", file=sys.stderr)
        return 2
    if not args.policy.exists():
        print(f"ERROR: policy not found: {args.policy}", file=sys.stderr)
        return 2

    toolbar, report = organize(args.source, args.policy)
    if not args.dry_run:
        output = args.output or args.source.with_name(args.source.stem + "_organized.html")
        output.write_text(render_netscape(toolbar), encoding="utf-8")
        print(f"Output: {output}")
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {args.report}")

    print(f"Input bookmarks: {report['input_bookmarks']}")
    print(f"Output bookmarks: {report['output_bookmarks']}")
    print(f"Duplicates removed: {report['duplicates_removed']}")
    print(f"Pending: {report['old_pending']} -> {report['new_pending']}")
    print(f"Path moves: {report['path_moves']}")
    print(f"Top-level moves: {report['top_level_moves']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
