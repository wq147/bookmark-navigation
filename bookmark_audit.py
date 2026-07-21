#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bookmark_audit.py

Audit Chrome / Edge Netscape Bookmark HTML exports without modifying them.
Standard library only. Python 3.9+ recommended.

Examples:
    python bookmark_audit.py bookmarks.html
    python bookmark_audit.py bookmarks.html -o report.md --json report.json
    python bookmark_audit.py bookmarks.html --check-links --workers 12 --timeout 8
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import html
import ipaddress
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional


TRACKING_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "yclid",
    "mc_cid",
    "mc_eid",
}

SENSITIVE_QUERY_KEYS = {
    "access_token",
    "auth",
    "authorization",
    "api_key",
    "apikey",
    "api-token",
    "key",
    "passwd",
    "password",
    "secret",
    "session",
    "sessionid",
    "sign",
    "signature",
    "ticket",
    "token",
}

SYSTEM_EMPTY_ALLOWED = {"00_待整理", "90_历史归档"}

CORE_SMALL_FOLDER_EXCEPTIONS = {
    "H3C",
    "华为",
    "Codex、OpenCode 与 AI 编程",
    "模型与本地部署",
    "AI 自动化与集成",
    "OpenWrt",
    "软路由与虚拟化",
    "5G 与 MIFI",
    "PCDN",
    "macOS 与 Homebrew",
}

GENERIC_FOLDER_NAMES = {
    "其他",
    "杂项",
    "综合",
    "常用工具",
    "实用工具",
    "软件",
    "玩机",
    "资料",
    "教程",
}


def load_policy_settings(policy_path: Optional[Path]) -> None:
    """Load audit exceptions and generic folder names from external policy JSON."""
    global CORE_SMALL_FOLDER_EXCEPTIONS, GENERIC_FOLDER_NAMES
    if not policy_path or not policy_path.exists():
        return
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    core = data.get("core_small_folders")
    generic = data.get("generic_folder_names")
    if isinstance(core, list):
        CORE_SMALL_FOLDER_EXCEPTIONS = {str(x) for x in core}
    if isinstance(generic, list):
        GENERIC_FOLDER_NAMES = {str(x) for x in generic}


NUMBER_PREFIX_RE = re.compile(r"^(\d{2})_(.+)$")
EXPECTED_TOP_LEVEL_NUMBERS = [0, *range(1, 12), 90]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36 BookmarkAudit/1.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


@dataclasses.dataclass
class Bookmark:
    title: str
    href: str
    folder_path: tuple[str, ...]
    attrs: dict[str, str]


@dataclasses.dataclass
class FolderInfo:
    path: tuple[str, ...]
    direct_links: int
    total_links: int
    subfolders: int


class NetscapeBookmarkParser(HTMLParser):
    """Parse Netscape Bookmark HTML into a lightweight tree."""

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
            self.stack[-1]["children"].append(
                {
                    "type": "link",
                    "title": "".join(self.text_buf).strip(),
                    "href": self.attrs_buf.get("href", ""),
                    "attrs": dict(self.attrs_buf),
                }
            )
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
    preferred = [
        folder
        for folder in folders
        if folder.get("attrs", {}).get("personal_toolbar_folder", "").lower() == "true"
    ]
    return preferred[0] if preferred else folders[0]


def walk_bookmarks(node: dict, path: tuple[str, ...] = ()) -> Iterable[Bookmark]:
    for child in node["children"]:
        if child["type"] == "folder":
            yield from walk_bookmarks(child, path + (child["title"],))
        else:
            yield Bookmark(
                title=child.get("title", ""),
                href=child.get("href", ""),
                folder_path=path,
                attrs=dict(child.get("attrs", {})),
            )


def count_total_links(node: dict) -> int:
    total = 0
    for child in node["children"]:
        if child["type"] == "link":
            total += 1
        else:
            total += count_total_links(child)
    return total


def walk_folders(node: dict, path: tuple[str, ...] = ()) -> Iterable[FolderInfo]:
    for child in node["children"]:
        if child["type"] != "folder":
            continue
        child_path = path + (child["title"],)
        direct = sum(1 for item in child["children"] if item["type"] == "link")
        subfolders = sum(1 for item in child["children"] if item["type"] == "folder")
        yield FolderInfo(
            path=child_path,
            direct_links=direct,
            total_links=count_total_links(child),
            subfolders=subfolders,
        )
        yield from walk_folders(child, child_path)


def normalize_url(url: str) -> str:
    """Normalize URL conservatively for duplicate detection."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return url

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        return url
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query_pairs = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in TRACKING_KEYS or key_lower.startswith("utm_"):
            continue
        query_pairs.append((key, value))
    query = urllib.parse.urlencode(query_pairs, doseq=True)

    fragment = parsed.fragment
    if fragment.startswith(":~:text="):
        fragment = ""

    return urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))


def normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(title or "")).strip().casefold()


def is_private_or_local_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return False


def has_sensitive_query(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    keys = {key.lower() for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)}
    return bool(keys & SENSITIVE_QUERY_KEYS)


def redact_url(url: str, show_sensitive: bool = False) -> str:
    if show_sensitive:
        return url
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return "<invalid URL>"
    if not parsed.scheme:
        return url
    safe_query = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_KEYS:
            safe_query.append((key, "***REDACTED***"))
        else:
            safe_query.append((key, value))
    query = urllib.parse.urlencode(safe_query, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def folder_str(path: tuple[str, ...]) -> str:
    return " / ".join(path) if path else "(根目录)"


def markdown_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def strip_folder_number(name: str) -> str:
    clean = (name or "").strip()
    match = NUMBER_PREFIX_RE.match(clean)
    return match.group(2).strip() if match else clean


def folder_number(name: str) -> Optional[int]:
    match = NUMBER_PREFIX_RE.match((name or "").strip())
    return int(match.group(1)) if match else None


def is_generic_folder_name(name: str) -> bool:
    clean = strip_folder_number(name)
    return clean in GENERIC_FOLDER_NAMES or clean.startswith("其他")


def audit_folder_numbering(toolbar: dict) -> dict:
    """Validate top-level and nested two-digit folder numbering.

    Top-level folders use the fixed personal sequence 00, 01..11, 90.
    Every nested sibling group uses a local contiguous sequence 01..N.
    """
    top_folders = [child for child in toolbar["children"] if child["type"] == "folder"]
    top_numbers = [folder_number(folder["title"]) for folder in top_folders]
    top_issues: list[str] = []

    if any(number is None for number in top_numbers):
        missing = [folder["title"] for folder, number in zip(top_folders, top_numbers) if number is None]
        top_issues.append("一级目录缺少两位编号：" + "、".join(missing))

    present_top = [number for number in top_numbers if number is not None]
    duplicate_top = sorted(number for number, count in Counter(present_top).items() if count > 1)
    if duplicate_top:
        top_issues.append("一级目录存在重复编号：" + "、".join(f"{number:02d}" for number in duplicate_top))

    if present_top and present_top != sorted(present_top, key=lambda n: (n == 90, n)):
        top_issues.append("一级目录显示顺序与编号顺序不一致")

    missing_subfolders: list[str] = []
    duplicate_groups: list[dict] = []
    gap_groups: list[dict] = []
    order_groups: list[str] = []

    def recurse(parent: dict, parent_path: tuple[str, ...]) -> None:
        children = [child for child in parent["children"] if child["type"] == "folder"]
        if children:
            numbers = [folder_number(child["title"]) for child in children]
            for child, number in zip(children, numbers):
                if number is None:
                    missing_subfolders.append(folder_str(parent_path + (child["title"],)))

            present = [number for number in numbers if number is not None]
            duplicates = sorted(number for number, count in Counter(present).items() if count > 1)
            if duplicates:
                duplicate_groups.append({
                    "parent": folder_str(parent_path),
                    "numbers": [f"{number:02d}" for number in duplicates],
                })

            if len(present) == len(children):
                expected = set(range(1, len(children) + 1))
                actual = set(present)
                missing_numbers = sorted(expected - actual)
                unexpected_numbers = sorted(actual - expected)
                if missing_numbers or unexpected_numbers:
                    gap_groups.append({
                        "parent": folder_str(parent_path),
                        "missing": [f"{number:02d}" for number in missing_numbers],
                        "unexpected": [f"{number:02d}" for number in unexpected_numbers],
                    })
                if present != sorted(present):
                    order_groups.append(folder_str(parent_path))

        for child in children:
            recurse(child, parent_path + (child["title"],))

    for top_folder in top_folders:
        recurse(top_folder, (top_folder["title"],))

    return {
        "top_level_issues": top_issues,
        "missing_subfolder_numbers": missing_subfolders,
        "duplicate_subfolder_number_groups": duplicate_groups,
        "subfolder_number_gap_groups": gap_groups,
        "subfolder_order_issues": order_groups,
    }


def check_http_url(url: str, timeout: float) -> dict:
    started = time.monotonic()

    def do_request(method: str) -> tuple[int, str]:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.getcode() or 0), response.geturl()

    try:
        status, final_url = do_request("HEAD")
        if status in {400, 403, 405, 429, 500, 501}:
            req = urllib.request.Request(
                url,
                headers={**DEFAULT_HEADERS, "Range": "bytes=0-1023"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status = int(response.getcode() or 0)
                final_url = response.geturl()
        return {
            "ok": 200 <= status < 400,
            "status": status,
            "error": "",
            "final_url": final_url,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except urllib.error.HTTPError as exc:
        return {
            "ok": 200 <= exc.code < 400,
            "status": int(exc.code),
            "error": str(exc.reason),
            "final_url": getattr(exc, "url", url),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return {
            "ok": False,
            "status": 0,
            "error": str(reason),
            "final_url": url,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


def audit(
    source_path: Path,
    small_threshold: int,
    large_threshold: int,
    check_links: bool,
    timeout: float,
    workers: int,
    show_sensitive: bool,
) -> dict:
    root = parse_bookmark_file(source_path)
    toolbar = find_toolbar_root(root)
    bookmarks = list(walk_bookmarks(toolbar))
    folders = list(walk_folders(toolbar))
    numbering = audit_folder_numbering(toolbar)

    url_groups: dict[str, list[Bookmark]] = defaultdict(list)
    title_groups: dict[str, list[Bookmark]] = defaultdict(list)
    for bookmark in bookmarks:
        url_groups[normalize_url(bookmark.href)].append(bookmark)
        title_groups[normalized_title(bookmark.title)].append(bookmark)

    duplicate_urls = {
        key: value for key, value in url_groups.items() if key and len(value) > 1
    }
    duplicate_titles = {
        key: value for key, value in title_groups.items() if key and len(value) > 1
    }

    empty_folders = [
        folder
        for folder in folders
        if folder.total_links == 0
        and not (len(folder.path) == 1 and folder.path[0] in SYSTEM_EMPTY_ALLOWED)
    ]
    all_small_leaf_folders = [
        folder
        for folder in folders
        if folder.subfolders == 0 and 0 < folder.total_links <= small_threshold
    ]
    core_small_leaf_folders = [
        folder for folder in all_small_leaf_folders if strip_folder_number(folder.path[-1]) in CORE_SMALL_FOLDER_EXCEPTIONS
    ]
    small_leaf_folders = [
        folder for folder in all_small_leaf_folders if strip_folder_number(folder.path[-1]) not in CORE_SMALL_FOLDER_EXCEPTIONS
    ]
    large_folders = [
        folder
        for folder in folders
        if folder.direct_links >= large_threshold
        or (folder.subfolders == 0 and folder.total_links >= large_threshold)
    ]
    generic_folders = [folder for folder in folders if is_generic_folder_name(folder.path[-1])]

    private_or_local = [bookmark for bookmark in bookmarks if is_private_or_local_url(bookmark.href)]
    sensitive_urls = [bookmark for bookmark in bookmarks if has_sensitive_query(bookmark.href)]
    non_http = [
        bookmark
        for bookmark in bookmarks
        if urllib.parse.urlsplit(bookmark.href).scheme.lower() not in {"http", "https"}
    ]

    pending_count = sum(
        1 for bookmark in bookmarks if bookmark.folder_path and bookmark.folder_path[0] == "00_待整理"
    )
    archive_count = sum(
        1 for bookmark in bookmarks if bookmark.folder_path and bookmark.folder_path[0] == "90_历史归档"
    )

    top_level_counts = Counter(
        bookmark.folder_path[0] if bookmark.folder_path else "(根目录)" for bookmark in bookmarks
    )

    link_results: list[dict] = []
    skipped_checks: list[dict] = []
    if check_links:
        candidates: list[Bookmark] = []
        for bookmark in bookmarks:
            scheme = urllib.parse.urlsplit(bookmark.href).scheme.lower()
            if scheme not in {"http", "https"}:
                skipped_checks.append({"bookmark": bookmark, "reason": "非 HTTP/HTTPS"})
            elif is_private_or_local_url(bookmark.href):
                skipped_checks.append({"bookmark": bookmark, "reason": "私网或本地地址"})
            elif has_sensitive_query(bookmark.href):
                skipped_checks.append({"bookmark": bookmark, "reason": "疑似含敏感查询参数"})
            else:
                candidates.append(bookmark)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            future_map = {
                executor.submit(check_http_url, bookmark.href, timeout): bookmark
                for bookmark in candidates
            }
            for future in concurrent.futures.as_completed(future_map):
                bookmark = future_map[future]
                result = future.result()
                link_results.append(
                    {
                        "title": bookmark.title,
                        "folder_path": bookmark.folder_path,
                        "url": redact_url(bookmark.href, show_sensitive=show_sensitive),
                        **result,
                    }
                )
        link_results.sort(key=lambda item: (item["ok"], item["status"], item["title"].casefold()))

    def bookmark_payload(bookmark: Bookmark) -> dict:
        return {
            "title": bookmark.title,
            "folder": folder_str(bookmark.folder_path),
            "url": redact_url(bookmark.href, show_sensitive=show_sensitive),
        }

    return {
        "source": str(source_path.resolve()),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "bookmarks": len(bookmarks),
            "folders": len(folders),
            "duplicate_url_groups": len(duplicate_urls),
            "duplicate_url_items": sum(len(items) - 1 for items in duplicate_urls.values()),
            "duplicate_title_groups": len(duplicate_titles),
            "empty_folders": len(empty_folders),
            "small_leaf_folders": len(small_leaf_folders),
            "core_small_leaf_folders": len(core_small_leaf_folders),
            "large_folders": len(large_folders),
            "generic_folders": len(generic_folders),
            "top_level_numbering_issues": len(numbering["top_level_issues"]),
            "missing_subfolder_numbers": len(numbering["missing_subfolder_numbers"]),
            "duplicate_subfolder_number_groups": len(numbering["duplicate_subfolder_number_groups"]),
            "subfolder_number_gap_groups": len(numbering["subfolder_number_gap_groups"]),
            "subfolder_order_issues": len(numbering["subfolder_order_issues"]),
            "pending": pending_count,
            "archive": archive_count,
            "private_or_local_urls": len(private_or_local),
            "sensitive_urls": len(sensitive_urls),
            "non_http_urls": len(non_http),
            "checked_links": len(link_results),
            "skipped_link_checks": len(skipped_checks),
        },
        "top_level_counts": dict(top_level_counts),
        "duplicate_urls": [
            {
                "normalized_url": redact_url(normalized, show_sensitive=show_sensitive),
                "items": [bookmark_payload(item) for item in items],
            }
            for normalized, items in sorted(duplicate_urls.items())
        ],
        "duplicate_titles": [
            {
                "normalized_title": title,
                "items": [bookmark_payload(item) for item in items],
            }
            for title, items in sorted(duplicate_titles.items())
        ],
        "empty_folders": [folder_str(folder.path) for folder in empty_folders],
        "small_leaf_folders": [
            {"folder": folder_str(folder.path), "count": folder.total_links}
            for folder in sorted(small_leaf_folders, key=lambda item: (item.total_links, item.path))
        ],
        "core_small_leaf_folders": [
            {"folder": folder_str(folder.path), "count": folder.total_links}
            for folder in sorted(core_small_leaf_folders, key=lambda item: (item.total_links, item.path))
        ],
        "large_folders": [
            {
                "folder": folder_str(folder.path),
                "direct_links": folder.direct_links,
                "total_links": folder.total_links,
            }
            for folder in sorted(large_folders, key=lambda item: (-item.direct_links, item.path))
        ],
        "generic_folders": [folder_str(folder.path) for folder in generic_folders],
        "numbering": numbering,
        "private_or_local_urls": [bookmark_payload(item) for item in private_or_local],
        "sensitive_urls": [bookmark_payload(item) for item in sensitive_urls],
        "non_http_urls": [bookmark_payload(item) for item in non_http],
        "link_results": link_results,
        "skipped_link_checks": [
            {**bookmark_payload(item["bookmark"]), "reason": item["reason"]}
            for item in skipped_checks
        ],
        "thresholds": {
            "small_threshold": small_threshold,
            "large_threshold": large_threshold,
        },
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines: list[str] = [
        "# 书签审计报告",
        "",
        f"- 源文件：`{markdown_escape(report['source'])}`",
        f"- 生成时间：{report['generated_at']}",
        "",
        "## 1. 总览",
        "",
        "| 指标 | 数量 |",
        "|---|---:|",
        f"| 书签 | {summary['bookmarks']} |",
        f"| 文件夹 | {summary['folders']} |",
        f"| 重复 URL 组 | {summary['duplicate_url_groups']} |",
        f"| 多余重复 URL 项 | {summary['duplicate_url_items']} |",
        f"| 重复标题组 | {summary['duplicate_title_groups']} |",
        f"| 空目录 | {summary['empty_folders']} |",
        f"| 小型叶子目录（建议检查） | {summary['small_leaf_folders']} |",
        f"| 核心主线小目录（规则允许） | {summary['core_small_leaf_folders']} |",
        f"| 大目录 | {summary['large_folders']} |",
        f"| 泛化目录名 | {summary['generic_folders']} |",
        f"| 一级目录编号问题 | {summary['top_level_numbering_issues']} |",
        f"| 子目录缺少编号 | {summary['missing_subfolder_numbers']} |",
        f"| 子目录重复编号组 | {summary['duplicate_subfolder_number_groups']} |",
        f"| 子目录缺号/越界组 | {summary['subfolder_number_gap_groups']} |",
        f"| 子目录顺序与编号不一致 | {summary['subfolder_order_issues']} |",
        f"| `00_待整理` | {summary['pending']} |",
        f"| `90_历史归档` | {summary['archive']} |",
        f"| 私网/本地 URL | {summary['private_or_local_urls']} |",
        f"| 疑似含敏感参数 URL | {summary['sensitive_urls']} |",
        f"| 非 HTTP/HTTPS 链接 | {summary['non_http_urls']} |",
        "",
        "## 2. 一级分类数量",
        "",
        "| 一级目录 | 书签数 |",
        "|---|---:|",
    ]

    for name, count in report["top_level_counts"].items():
        lines.append(f"| {markdown_escape(name)} | {count} |")

    lines += ["", "## 3. 重复 URL", ""]
    if not report["duplicate_urls"]:
        lines.append("未发现重复 URL。重复标题不一定表示重复书签，可能是同名页面或不同入口。")
    else:
        for index, group in enumerate(report["duplicate_urls"], start=1):
            lines.append(f"### 3.{index} `{markdown_escape(group['normalized_url'])}`")
            lines.append("")
            for item in group["items"]:
                lines.append(
                    f"- **{markdown_escape(item['title'])}** — `{markdown_escape(item['folder'])}`"
                )
            lines.append("")

    lines += ["", "## 4. 目录结构建议", ""]

    lines.append(
        f"### 小型叶子目录（≤ {report['thresholds']['small_threshold']} 个书签，建议检查）"
    )
    lines.append("")
    if not report["small_leaf_folders"]:
        lines.append("无。")
    else:
        for item in report["small_leaf_folders"]:
            lines.append(f"- `{markdown_escape(item['folder'])}`：{item['count']} 个")

    lines += ["", "### 核心主线小目录（按规则可保留）", ""]
    if not report["core_small_leaf_folders"]:
        lines.append("无。")
    else:
        for item in report["core_small_leaf_folders"]:
            lines.append(f"- `{markdown_escape(item['folder'])}`：{item['count']} 个")

    lines += ["", f"### 大目录（≥ {report['thresholds']['large_threshold']} 个直接书签）", ""]
    if not report["large_folders"]:
        lines.append("无。")
    else:
        for item in report["large_folders"]:
            lines.append(
                f"- `{markdown_escape(item['folder'])}`：直接 {item['direct_links']} 个，总计 {item['total_links']} 个"
            )

    lines += ["", "### 泛化目录名", ""]
    if not report["generic_folders"]:
        lines.append("未发现。")
    else:
        for item in report["generic_folders"]:
            lines.append(f"- `{markdown_escape(item)}`")

    lines += ["", "### 空目录", ""]
    if not report["empty_folders"]:
        lines.append("无。")
    else:
        for item in report["empty_folders"]:
            lines.append(f"- `{markdown_escape(item)}`")

    lines += ["", "## 5. 目录编号检查", ""]
    numbering = report["numbering"]
    numbering_ok = not any([
        numbering["top_level_issues"],
        numbering["missing_subfolder_numbers"],
        numbering["duplicate_subfolder_number_groups"],
        numbering["subfolder_number_gap_groups"],
        numbering["subfolder_order_issues"],
    ])
    if numbering_ok:
        lines.append("编号检查通过：一级目录保持固定编号，所有子目录均使用父目录内局部连续的 `01_`、`02_`……编号。")
    else:
        if numbering["top_level_issues"]:
            lines += ["", "### 一级目录编号问题", ""]
            for item in numbering["top_level_issues"]:
                lines.append(f"- {markdown_escape(item)}")
        if numbering["missing_subfolder_numbers"]:
            lines += ["", "### 缺少编号的子目录", ""]
            for item in numbering["missing_subfolder_numbers"]:
                lines.append(f"- `{markdown_escape(item)}`")
        if numbering["duplicate_subfolder_number_groups"]:
            lines += ["", "### 重复编号", ""]
            for item in numbering["duplicate_subfolder_number_groups"]:
                lines.append(f"- `{markdown_escape(item['parent'])}`：{', '.join(item['numbers'])}")
        if numbering["subfolder_number_gap_groups"]:
            lines += ["", "### 缺号或越界编号", ""]
            for item in numbering["subfolder_number_gap_groups"]:
                detail = []
                if item["missing"]:
                    detail.append("缺少 " + ", ".join(item["missing"]))
                if item["unexpected"]:
                    detail.append("异常 " + ", ".join(item["unexpected"]))
                lines.append(f"- `{markdown_escape(item['parent'])}`：{'；'.join(detail)}")
        if numbering["subfolder_order_issues"]:
            lines += ["", "### 显示顺序与编号顺序不一致", ""]
            for item in numbering["subfolder_order_issues"]:
                lines.append(f"- `{markdown_escape(item)}`")

    lines += ["", "## 6. 隐私与安全提示", ""]
    lines.append(
        "报告默认对疑似敏感查询参数做脱敏；私网/本地 URL 不会在联网检查中访问。"
    )
    lines.append("")
    lines.append(f"- 私网/本地 URL：{summary['private_or_local_urls']} 个")
    lines.append(f"- 疑似含敏感查询参数 URL：{summary['sensitive_urls']} 个")

    lines += ["", "## 7. 联网状态检查", ""]
    if report["link_results"]:
        failed = [item for item in report["link_results"] if not item["ok"]]
        lines.append(
            f"已检查 {summary['checked_links']} 个，跳过 {summary['skipped_link_checks']} 个，疑似异常 {len(failed)} 个。"
        )
        lines.append("")
        if failed:
            lines += [
                "| 状态 | 标题 | 目录 | URL / 错误 |",
                "|---:|---|---|---|",
            ]
            for item in failed:
                status = item["status"] or "ERR"
                detail = item["error"] or item["url"]
                lines.append(
                    "| {status} | {title} | {folder} | {detail} |".format(
                        status=status,
                        title=markdown_escape(item["title"]),
                        folder=markdown_escape(folder_str(tuple(item["folder_path"]))),
                        detail=markdown_escape(detail),
                    )
                )
        else:
            lines.append("未发现明显异常。")
    else:
        lines.append("本次未启用联网检查。需要时运行：`python bookmark_audit.py bookmarks.html --check-links`。")

    lines += [
        "",
        "## 8. 建议处理顺序",
        "",
        "1. 先处理重复 URL。",
        "2. 再清空 `00_待整理`。",
        "3. 检查超过阈值的大目录是否需要拆分。",
        "4. 合并非长期主线的单书签目录。",
        "5. 清理泛化目录名和空目录。",
        "6. 最后再处理可能失效的外部链接。",
        "",
        "> 说明：联网状态检查只能作为参考。部分网站会阻止脚本请求，即使报告返回 403/429，浏览器中仍可能正常打开。",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="审计 Chrome / Edge 导出的 Netscape Bookmark HTML，不修改源文件。"
    )
    parser.add_argument("input", type=Path, help="书签 HTML 文件")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("bookmark_audit_report.md"),
        help="Markdown 报告路径（默认：bookmark_audit_report.md）",
    )
    parser.add_argument("--json", dest="json_output", type=Path, help="同时输出 JSON 报告")
    parser.add_argument(
        "--policy",
        type=Path,
        help="可选：读取 bookmark_policy.json 中的长期主线和泛化目录规则",
    )
    parser.add_argument(
        "--small-threshold",
        type=int,
        default=2,
        help="小型叶子目录阈值（默认：2）",
    )
    parser.add_argument(
        "--large-threshold",
        type=int,
        default=20,
        help="大目录阈值（默认：20）",
    )
    parser.add_argument(
        "--check-links",
        action="store_true",
        help="联网检查 HTTP/HTTPS 链接；默认跳过私网、本地和疑似敏感 URL",
    )
    parser.add_argument("--timeout", type=float, default=8.0, help="单链接超时秒数（默认：8）")
    parser.add_argument("--workers", type=int, default=12, help="联网检查并发数（默认：12）")
    parser.add_argument(
        "--show-sensitive",
        action="store_true",
        help="在报告中显示完整 URL；默认会对敏感查询参数脱敏",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if not args.input.exists():
        print(f"错误：文件不存在：{args.input}", file=sys.stderr)
        return 2
    if args.small_threshold < 0 or args.large_threshold < 1:
        print("错误：阈值参数无效。", file=sys.stderr)
        return 2

    policy_path = args.policy
    if policy_path is None:
        candidate = args.input.parent / "bookmark_policy.json"
        if candidate.exists():
            policy_path = candidate
    if policy_path is not None and not policy_path.exists():
        print(f"错误：策略文件不存在：{policy_path}", file=sys.stderr)
        return 2
    load_policy_settings(policy_path)

    report = audit(
        source_path=args.input,
        small_threshold=args.small_threshold,
        large_threshold=args.large_threshold,
        check_links=args.check_links,
        timeout=args.timeout,
        workers=args.workers,
        show_sensitive=args.show_sensitive,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(report), encoding="utf-8")
    print(f"Markdown 报告：{args.output.resolve()}")

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON 报告：{args.json_output.resolve()}")

    summary = report["summary"]
    print(
        "书签={bookmarks} 文件夹={folders} 重复URL组={duplicate_url_groups} "
        "待整理={pending} 历史归档={archive} 小目录={small_leaf_folders} 大目录={large_folders} 子目录缺编号={missing_subfolder_numbers}".format(
            **summary
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
