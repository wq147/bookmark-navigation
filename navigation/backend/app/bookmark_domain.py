"""Immutable bookmark-domain model and Netscape HTML adapter.

The parsing, rendering, and URL normalization algorithms intentionally live
here instead of importing the existing command-line scripts.  This keeps the
domain layer usable without triggering CLI concerns or network access.
"""

from __future__ import annotations

import html
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from types import MappingProxyType
from typing import Dict, Iterator, Mapping, Optional, Tuple, Union


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


def _immutable_attrs(attrs: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(attrs))


@dataclass(frozen=True)
class BookmarkNode:
    title: str
    url: str
    attrs: Mapping[str, str]
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "attrs", _immutable_attrs(self.attrs))


@dataclass(frozen=True)
class FolderNode:
    title: str
    attrs: Mapping[str, str]
    children: Tuple[Union["FolderNode", BookmarkNode], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attrs", _immutable_attrs(self.attrs))
        object.__setattr__(self, "children", tuple(_freeze_node(child) for child in self.children))


@dataclass(frozen=True)
class BookmarkRecord:
    title: str
    url: str
    path: Tuple[str, ...]
    attrs: Mapping[str, str]
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", tuple(self.path))
        object.__setattr__(self, "attrs", _immutable_attrs(self.attrs))


def _freeze_node(node: Union[FolderNode, BookmarkNode]) -> Union[FolderNode, BookmarkNode]:
    if isinstance(node, FolderNode):
        return FolderNode(node.title, node.attrs, node.children)
    if isinstance(node, BookmarkNode):
        return BookmarkNode(node.title, node.url, node.attrs, node.notes)
    raise TypeError("folder children must be FolderNode or BookmarkNode instances")


@dataclass(frozen=True)
class BookmarkTree:
    root: FolderNode

    def __post_init__(self) -> None:
        if not isinstance(self.root, FolderNode):
            raise TypeError("bookmark tree root must be a FolderNode")
        object.__setattr__(self, "root", _freeze_node(self.root))

    @classmethod
    def from_legacy_root(cls, legacy_root: dict) -> "BookmarkTree":
        folders = [item for item in legacy_root["children"] if item["type"] == "folder"]
        preferred = [
            folder
            for folder in folders
            if folder.get("attrs", {}).get("personal_toolbar_folder", "").lower() == "true"
        ]
        toolbar = preferred[0] if preferred else (folders[0] if folders else legacy_root)
        return cls(_folder_from_legacy(toolbar))

    def bookmarks(self) -> Tuple[BookmarkRecord, ...]:
        return tuple(iter_bookmarks(self))


def _folder_from_legacy(folder: dict) -> FolderNode:
    children = []
    for child in folder.get("children", []):
        if child["type"] == "folder":
            children.append(_folder_from_legacy(child))
        else:
            children.append(
                BookmarkNode(
                    title=child.get("title", ""),
                    url=child.get("href", ""),
                    attrs=_immutable_attrs(child.get("attrs", {})),
                    notes=child.get("notes", ""),
                )
            )
    return FolderNode(
        title=folder.get("title", ""),
        attrs=_immutable_attrs(folder.get("attrs", {})),
        children=tuple(children),
    )


class NetscapeBookmarkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = {"type": "folder", "title": "ROOT", "attrs": {}, "children": []}
        self.stack = [self.root]
        self.capture: Optional[str] = None
        self.text_buf = []
        self.attrs_buf: Dict[str, str] = {}
        self.pending_folder: Optional[dict] = None
        self.last_link: Optional[dict] = None
        self.outer_dl_depth = 0

    def _finish_description(self) -> None:
        if self.capture != "dd":
            return
        if self.last_link is not None:
            self.last_link["notes"] = "".join(self.text_buf).strip()
        self.capture = None
        self.text_buf = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self.capture == "dd" and tag in {"a", "dd", "dl", "dt", "h3"}:
            self._finish_description()
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        if tag == "h3":
            self.capture = "h3"
            self.text_buf = []
            self.attrs_buf = attr_map
        elif tag == "a":
            self.capture = "a"
            self.text_buf = []
            self.attrs_buf = attr_map
        elif tag == "dd":
            self.capture = "dd"
            self.text_buf = []
        elif tag == "dl":
            if self.pending_folder is not None:
                self.stack[-1]["children"].append(self.pending_folder)
                self.stack.append(self.pending_folder)
                self.pending_folder = None
            else:
                self.outer_dl_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.capture == "dd" and tag in {"dd", "dl"}:
            self._finish_description()
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
            link = {
                "type": "link",
                "title": "".join(self.text_buf).strip(),
                "href": self.attrs_buf.get("href", ""),
                "attrs": dict(self.attrs_buf),
                "notes": "",
            }
            self.stack[-1]["children"].append(link)
            self.last_link = link
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

    def close(self) -> None:
        super().close()
        self._finish_description()


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
    path = "" if parts.path == "/" else (parts.path or "")
    if path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_KEYS and not key.lower().startswith("utm_")
    ]
    query = urllib.parse.urlencode(query_pairs, doseq=True)
    fragment = "" if parts.fragment.startswith(":~:text=") else parts.fragment
    return urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))


def parse_html(content: str) -> BookmarkTree:
    parser = NetscapeBookmarkParser()
    parser.feed(content)
    parser.close()
    return BookmarkTree.from_legacy_root(parser.root)


def iter_bookmarks(tree: BookmarkTree) -> Iterator[BookmarkRecord]:
    def walk(folder: FolderNode, path: Tuple[str, ...]) -> Iterator[BookmarkRecord]:
        for child in folder.children:
            if isinstance(child, FolderNode):
                yield from walk(child, path + (child.title,))
            else:
                yield BookmarkRecord(child.title, child.url, path, child.attrs, child.notes)

    yield from walk(tree.root, ())


def _attr_text(attrs: Mapping[str, str], href: Optional[str] = None) -> str:
    values = dict(attrs)
    if href is not None:
        values["href"] = href
    preferred = ["href", "add_date", "last_modified", "icon", "shortcuturl", "tags"]
    keys = [key for key in preferred if key in values]
    keys.extend(key for key in values if key not in keys)
    return " ".join(
        '{}="{}"'.format(key.upper(), html.escape(str(values[key]), quote=True))
        for key in keys
        if values[key] is not None
    )


def render_html(tree: BookmarkTree) -> str:
    root_attrs = dict(tree.root.attrs)
    root_attrs.setdefault("personal_toolbar_folder", "true")
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
        '    <DT><H3 {}>{}</H3>'.format(_attr_text(root_attrs), html.escape(tree.root.title)),
        "    <DL><p>",
    ]

    def emit(folder: FolderNode, level: int) -> None:
        indent = "    " * level
        for child in folder.children:
            if isinstance(child, FolderNode):
                attrs = _attr_text(child.attrs)
                spacer = " " if attrs else ""
                lines.append(
                    '{}<DT><H3{}{}>{}</H3>'.format(
                        indent, spacer, attrs, html.escape(child.title)
                    )
                )
                lines.append("{}<DL><p>".format(indent))
                emit(child, level + 1)
                lines.append("{}</DL><p>".format(indent))
            else:
                lines.append(
                    '{}<DT><A {}>{}</A>'.format(
                        indent, _attr_text(child.attrs, child.url), html.escape(child.title)
                    )
                )
                if child.notes:
                    lines.append("{}<DD>{}".format(indent, html.escape(child.notes)))

    emit(tree.root, 2)
    lines.extend(["    </DL><p>", "</DL><p>"])
    return "\n".join(lines) + "\n"
