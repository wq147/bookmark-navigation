#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bookmark_numbering.py

Renumber nested bookmark folders using bookmark_policy.json.
Folder order is externalized in the policy file; edit JSON instead of Python.

Examples:
    python3 bookmark_numbering.py bookmarks.html -o bookmarks_numbered.html
    python3 bookmark_numbering.py bookmarks.html --policy bookmark_policy.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Optional

from bookmark_organizer import (
    parse_bookmark_file,
    find_toolbar_root,
    number_nested_folders,
    render_netscape,
)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Renumber nested bookmark folders using external policy JSON.")
    parser.add_argument("source", type=Path, help="Chrome/Edge Netscape bookmark HTML export")
    parser.add_argument("-o", "--output", type=Path, help="Output HTML path")
    parser.add_argument("--policy", type=Path, default=Path("bookmark_policy.json"), help="Policy JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only; do not write output")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if not args.source.exists():
        print(f"ERROR: source not found: {args.source}", file=sys.stderr)
        return 2
    if not args.policy.exists():
        print(f"ERROR: policy not found: {args.policy}", file=sys.stderr)
        return 2

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    root = parse_bookmark_file(args.source)
    toolbar = find_toolbar_root(root)
    toolbar_copy = deepcopy(toolbar)
    changed = number_nested_folders(toolbar_copy, policy)

    print(f"Folders renamed/reordered: {changed}")
    if not args.dry_run:
        output = args.output or args.source.with_name(args.source.stem + "_numbered.html")
        output.write_text(render_netscape(toolbar_copy), encoding="utf-8")
        print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
