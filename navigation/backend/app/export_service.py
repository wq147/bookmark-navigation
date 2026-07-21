"""Audited portable exports of the persisted bookmark hierarchy."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookmark_domain import (
    BookmarkNode,
    BookmarkTree,
    FolderNode,
    normalize_url,
    render_html,
)
from app.models import Bookmark, Folder, Operation
from app.import_service import load_policy


class ExportAuditError(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


NUMBERED_NAME = re.compile(r"^\d{1,3}[_\-\s、.]+")


def _numbered_name(folder: Folder, fixed_top_level: set[str]) -> str:
    if folder.parent_id is None and folder.base_name in fixed_top_level:
        return folder.base_name
    base_name = NUMBERED_NAME.sub("", folder.base_name).strip()
    return f"{folder.position:02d}_{base_name}"


def _load(session: Session, user_id: int) -> tuple[list[Folder], list[Bookmark]]:
    folders = list(
        session.scalars(
            select(Folder)
            .where(Folder.user_id == user_id)
            .order_by(Folder.parent_id, Folder.position, Folder.id)
        )
    )
    bookmarks = list(
        session.scalars(
            select(Bookmark)
            .where(Bookmark.user_id == user_id, Bookmark.deleted_at.is_(None))
            .order_by(Bookmark.folder_id, Bookmark.position, Bookmark.id)
        )
    )
    return folders, bookmarks


def _audit(folders: list[Folder], bookmarks: list[Bookmark]) -> None:
    errors: list[str] = []
    by_id = {folder.id: folder for folder in folders}
    children: dict[int | None, list[Folder]] = {}
    for folder in folders:
        children.setdefault(folder.parent_id, []).append(folder)
        if folder.parent_id is not None and folder.parent_id not in by_id:
            errors.append(f"folder {folder.id} has a missing parent")
        seen = {folder.id}
        parent_id = folder.parent_id
        while parent_id is not None and parent_id in by_id:
            if parent_id in seen:
                errors.append(f"folder {folder.id} is in a cycle")
                break
            seen.add(parent_id)
            parent_id = by_id[parent_id].parent_id
    for parent_id, siblings in children.items():
        positions = sorted(folder.position for folder in siblings)
        if positions != list(range(1, len(siblings) + 1)):
            errors.append(f"folders below {parent_id} are not continuously numbered")

    normalized: set[str] = set()
    for bookmark in bookmarks:
        if bookmark.folder_id not in by_id:
            errors.append(f"bookmark {bookmark.id} has a missing folder")
        expected = normalize_url(bookmark.url)
        if not expected or expected != bookmark.normalized_url:
            errors.append(f"bookmark {bookmark.id} has an invalid normalized URL")
        if expected in normalized:
            errors.append(f"bookmark {bookmark.id} duplicates a normalized URL")
        normalized.add(expected)
    if errors:
        raise ExportAuditError(errors)


def build_tree(session: Session, user_id: int) -> BookmarkTree:
    folders, bookmarks = _load(session, user_id)
    _audit(folders, bookmarks)
    folder_children: dict[int | None, list[Folder]] = {}
    bookmark_children: dict[int, list[Bookmark]] = {}
    for folder in folders:
        folder_children.setdefault(folder.parent_id, []).append(folder)
    for bookmark in bookmarks:
        bookmark_children.setdefault(bookmark.folder_id, []).append(bookmark)
    fixed_top_level = set(load_policy().get("top_level_order", []))

    def node(folder: Folder) -> FolderNode:
        nested = [node(child) for child in folder_children.get(folder.id, [])]
        links = [
            BookmarkNode(
                bookmark.title,
                bookmark.url,
                {
                    "add_date": str(int(bookmark.created_at.timestamp())),
                    **(bookmark.attrs or {}),
                },
                bookmark.notes,
            )
            for bookmark in bookmark_children.get(folder.id, [])
        ]
        return FolderNode(
            _numbered_name(folder, fixed_top_level),
            folder.attrs or {},
            tuple(nested + links),
        )

    toolbar_attrs = next(
        (
            folder.toolbar_attrs
            for folder in folder_children.get(None, [])
            if folder.toolbar_attrs
        ),
        {},
    )

    return BookmarkTree(
        FolderNode(
            "Bookmarks bar",
            {"personal_toolbar_folder": "true", **toolbar_attrs},
            tuple(node(folder) for folder in folder_children.get(None, [])),
        )
    )


def export_bookmarks_html(session: Session, user_id: int) -> str:
    return render_html(build_tree(session, user_id))


def export_backup_json(session: Session, user_id: int) -> dict[str, object]:
    folders, bookmarks = _load(session, user_id)
    _audit(folders, bookmarks)
    operations = list(
        session.scalars(
            select(Operation).where(Operation.user_id == user_id).order_by(Operation.id)
        ).all()
    )
    return {
        "format": "private-bookmark-navigation",
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "audit": {"folder_count": len(folders), "bookmark_count": len(bookmarks)},
        "folders": [
            {
                "id": folder.id,
                "parent_id": folder.parent_id,
                "base_name": folder.base_name,
                "position": folder.position,
                "attrs": folder.attrs or {},
                "toolbar_attrs": folder.toolbar_attrs or {},
            }
            for folder in folders
        ],
        "bookmarks": [
            {
                "id": bookmark.id,
                "folder_id": bookmark.folder_id,
                "title": bookmark.title,
                "url": bookmark.url,
                "normalized_url": bookmark.normalized_url,
                "notes": bookmark.notes,
                "position": bookmark.position,
                "attrs": bookmark.attrs or {},
            }
            for bookmark in bookmarks
        ],
        "operations": [
            {
                "id": operation.id,
                "operation_type": operation.operation_type,
                "payload": json.loads(operation.payload),
                "created_at": operation.created_at.replace(tzinfo=UTC).isoformat(),
            }
            for operation in operations
        ],
    }
