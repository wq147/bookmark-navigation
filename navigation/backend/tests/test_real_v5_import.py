import os
from dataclasses import replace
from pathlib import Path

import pytest

from app.bookmark_domain import FolderNode, normalize_url, parse_html

from test_imports import auth_client, session_factory  # noqa: F401

PRIVATE_FIXTURE_VALUE = os.getenv("NAV_PRIVATE_BOOKMARK_FIXTURE")
PRIVATE_FIXTURE_PATH = (
    Path(PRIVATE_FIXTURE_VALUE).expanduser() if PRIVATE_FIXTURE_VALUE else None
)


def _folder_attrs(tree):
    result = {}

    def walk(folder, path):
        for child in folder.children:
            if isinstance(child, FolderNode):
                child_path = path + (child.title,)
                result[child_path] = dict(child.attrs)
                walk(child, child_path)

    walk(tree.root, ())
    return result


def _bookmark_state(records):
    return {
        normalize_url(record.url): (record.path, dict(record.attrs))
        for record in records
    }


def test_bookmark_state_detects_swapped_paths():
    content = b"""<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p><DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3><DL><p>
<DT><H3>01_A</H3><DL><p><DT><A HREF="https://a.test" ADD_DATE="1">A</A></DL><p>
<DT><H3>02_B</H3><DL><p><DT><A HREF="https://b.test" ADD_DATE="2">B</A></DL><p>
</DL><p></DL><p>"""
    records = parse_html(content.decode()).bookmarks()
    swapped = (
        replace(records[0], path=records[1].path),
        replace(records[1], path=records[0].path),
    )
    with pytest.raises(AssertionError):
        assert _bookmark_state(swapped) == _bookmark_state(records)


@pytest.mark.skipif(
    PRIVATE_FIXTURE_PATH is None or not PRIVATE_FIXTURE_PATH.is_file(),
    reason="set NAV_PRIVATE_BOOKMARK_FIXTURE to a private Netscape HTML fixture",
)
def test_private_fixture_import_round_trip_matches_source(auth_client):
    content = PRIVATE_FIXTURE_PATH.read_bytes()
    source_tree = parse_html(content.decode("utf-8-sig"))
    source_state = _bookmark_state(source_tree.bookmarks())
    preview = auth_client.post(
        "/api/v1/imports/preview",
        files={"file": ("private-fixture.html", content, "text/html")},
    )
    assert preview.status_code == 200
    assert preview.json()["summary"] == {
        "new": len(source_state),
        "duplicate": 0,
        "conflict": 0,
        "suggested_move": 0,
        "unclassified": 0,
    }
    result = auth_client.post(
        f"/api/v1/imports/{preview.json()['id']}/apply", json={"overrides": []}
    )
    assert result.status_code == 200
    assert result.json()["unique_bookmarks"] == len(source_state)
    assert result.json()["duplicate_urls"] == 0
    assert result.json()["unclassified"] == 0

    exported = auth_client.get("/api/v1/exports/bookmarks.html")
    assert exported.status_code == 200
    exported_tree = parse_html(exported.text)
    assert _folder_attrs(exported_tree) == _folder_attrs(source_tree)
    assert exported_tree.root.attrs == source_tree.root.attrs
    assert _bookmark_state(exported_tree.bookmarks()) == source_state
