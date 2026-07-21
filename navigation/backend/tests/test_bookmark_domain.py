from dataclasses import FrozenInstanceError

import pytest

from app.bookmark_domain import (
    BookmarkNode,
    BookmarkRecord,
    BookmarkTree,
    FolderNode,
    iter_bookmarks,
    normalize_url,
    parse_html,
    render_html,
)


SAMPLE = '''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p><DT><H3 PERSONAL_TOOLBAR_FOLDER="true">书签栏</H3><DL><p>
<DT><H3>02_AI 与智能开发</H3><DL><p>
<DT><A HREF="https://example.com/docs/?utm_source=x" ADD_DATE="1">Example</A>
</DL><p></DL><p></DL><p>'''

SAMPLE_WITH_NOTES = '''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p><DT><H3 PERSONAL_TOOLBAR_FOLDER="true">书签栏</H3><DL><p>
<DT><H3>01_常用</H3><DL><p>
<DT><A HREF="https://notes.test">Notes</A><DD>private &amp; useful
<DT><A HREF="https://second.test">Second</A>
</DL><p></DL><p></DL><p>'''


def test_normalize_url_removes_tracking_and_trailing_slash():
    assert normalize_url("https://EXAMPLE.com/docs/?utm_source=x") == "https://example.com/docs"


def test_parse_render_parse_preserves_path_and_attributes():
    first = parse_html(SAMPLE)
    second = parse_html(render_html(first))
    assert second.bookmarks()[0].path == ("02_AI 与智能开发",)
    assert second.bookmarks()[0].attrs["add_date"] == "1"


def test_parse_render_parse_preserves_standard_dd_bookmark_notes():
    first = parse_html(SAMPLE_WITH_NOTES)
    assert [record.notes for record in first.bookmarks()] == ["private & useful", ""]

    rendered = render_html(first)
    assert "<DD>private &amp; useful" in rendered
    assert [record.notes for record in parse_html(rendered).bookmarks()] == [
        "private & useful",
        "",
    ]


def test_iter_bookmarks_returns_records_in_document_order():
    tree = parse_html(SAMPLE)
    records = list(iter_bookmarks(tree))
    assert [(record.title, record.url) for record in records] == [
        ("Example", "https://example.com/docs/?utm_source=x")
    ]


def test_domain_nodes_are_immutable():
    tree = parse_html(SAMPLE)
    folder = tree.root.children[0]
    assert isinstance(folder, FolderNode)
    bookmark = folder.children[0]
    assert isinstance(bookmark, BookmarkNode)
    with pytest.raises(FrozenInstanceError):
        bookmark.title = "Changed"
    with pytest.raises(TypeError):
        bookmark.attrs["add_date"] = "2"


def test_direct_bookmark_node_defensively_freezes_attributes():
    attrs = {"add_date": "1"}
    node = BookmarkNode("Example", "https://example.com", attrs)
    attrs["add_date"] = "2"
    assert node.attrs["add_date"] == "1"
    with pytest.raises(TypeError):
        node.attrs["add_date"] = "3"


def test_direct_folder_node_defensively_freezes_attributes_and_children():
    attrs = {"add_date": "1"}
    children = [BookmarkNode("Example", "https://example.com", {})]
    folder = FolderNode("Folder", attrs, children)
    attrs["add_date"] = "2"
    children.clear()
    assert folder.attrs["add_date"] == "1"
    assert len(folder.children) == 1
    assert isinstance(folder.children, tuple)


def test_direct_bookmark_record_defensively_freezes_attributes_and_path():
    attrs = {"add_date": "1"}
    path = ["Folder"]
    record = BookmarkRecord("Example", "https://example.com", path, attrs)
    attrs["add_date"] = "2"
    path.append("Nested")
    assert record.attrs["add_date"] == "1"
    assert record.path == ("Folder",)
    with pytest.raises(TypeError):
        record.attrs["add_date"] = "3"


def test_direct_bookmark_tree_defensively_freezes_reachable_nodes():
    bookmark_attrs = {"add_date": "1"}
    folder_attrs = {"last_modified": "2"}
    children = [BookmarkNode("Example", "https://example.com", bookmark_attrs)]
    root = FolderNode("Root", folder_attrs, children)
    tree = BookmarkTree(root)
    bookmark_attrs["add_date"] = "changed"
    folder_attrs["last_modified"] = "changed"
    children.clear()
    assert tree.root.attrs["last_modified"] == "2"
    assert tree.root.children[0].attrs["add_date"] == "1"
    assert isinstance(tree.root.children, tuple)
