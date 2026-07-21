"""Transactional folder, bookmark, and search operations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.bookmark_domain import normalize_url
from app.models import Bookmark, Folder, Operation
from app.schemas import BookmarkCreate, BookmarkUpdate, FolderCreate, FolderUpdate


class ServiceError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ResourceNotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409


class DuplicateBookmark(Conflict):
    def __init__(self, existing_id: int) -> None:
        super().__init__("Bookmark URL already exists")
        self.existing_id = existing_id


def _parent_clause(parent_id: int | None):
    return Folder.parent_id.is_(None) if parent_id is None else Folder.parent_id == parent_id


def _folder_siblings(session: Session, user_id: int, parent_id: int | None) -> list[Folder]:
    return list(
        session.scalars(
            select(Folder)
            .where(Folder.user_id == user_id, _parent_clause(parent_id))
            .order_by(Folder.position, Folder.id)
        ).all()
    )


def _set_folder_order(session: Session, folders: list[Folder]) -> None:
    # Folder positions are unique per parent. A temporary negative pass avoids
    # transient uniqueness violations while compacting or reordering siblings.
    for temporary, folder in enumerate(folders, 1):
        folder.position = -temporary
    session.flush()
    for position, folder in enumerate(folders, 1):
        folder.position = position


def renumber_siblings(session: Session, user_id: int, parent_id: int | None) -> None:
    """Compact sibling folder positions to a stable one-based sequence."""

    _set_folder_order(session, _folder_siblings(session, user_id, parent_id))


def _record(session: Session, user_id: int, operation_type: str, **summary: object) -> None:
    session.add(
        Operation(
            user_id=user_id,
            operation_type=operation_type,
            payload=json.dumps(summary, ensure_ascii=False, sort_keys=True),
        )
    )


def _require_folder(session: Session, user_id: int, folder_id: int) -> Folder:
    folder = session.scalar(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
    )
    if folder is None:
        raise ResourceNotFound("Folder not found")
    return folder


def _check_folder_name(
    session: Session,
    user_id: int,
    parent_id: int | None,
    base_name: str,
    *,
    exclude_id: int | None = None,
) -> None:
    statement = select(Folder.id).where(
        Folder.user_id == user_id,
        _parent_clause(parent_id),
        Folder.base_name == base_name,
    )
    if exclude_id is not None:
        statement = statement.where(Folder.id != exclude_id)
    if session.scalar(statement) is not None:
        raise Conflict("A sibling folder with this name already exists")


def create_folder(session: Session, user_id: int, data: FolderCreate) -> Folder:
    if data.parent_id is not None:
        _require_folder(session, user_id, data.parent_id)
    base_name = data.base_name.strip()
    if not base_name:
        raise ServiceError("Folder name cannot be empty")
    _check_folder_name(session, user_id, data.parent_id, base_name)
    siblings = _folder_siblings(session, user_id, data.parent_id)
    append_position = max((sibling.position for sibling in siblings), default=0) + 1
    folder = Folder(
        user_id=user_id,
        parent_id=data.parent_id,
        base_name=base_name,
        position=append_position,
    )
    session.add(folder)
    session.flush()
    if data.position is not None:
        siblings.insert(min(data.position - 1, len(siblings)), folder)
        _set_folder_order(session, siblings)
    _record(session, user_id, "folder.create", folder_id=folder.id, parent_id=folder.parent_id)
    session.flush()
    return folder


def _ensure_no_cycle(
    session: Session, user_id: int, folder_id: int, parent_id: int | None
) -> None:
    ancestor_id = parent_id
    while ancestor_id is not None:
        if ancestor_id == folder_id:
            raise Conflict("Folder cannot be moved below itself or a descendant")
        ancestor = session.scalar(
            select(Folder).where(Folder.id == ancestor_id, Folder.user_id == user_id)
        )
        if ancestor is None:
            raise ResourceNotFound("Parent folder not found")
        ancestor_id = ancestor.parent_id


def update_folder(session: Session, user_id: int, folder_id: int, data: FolderUpdate) -> Folder:
    folder = _require_folder(session, user_id, folder_id)
    changes = data.model_dump(exclude_unset=True)
    old_parent_id = folder.parent_id
    new_parent_id = changes.get("parent_id", old_parent_id)
    _ensure_no_cycle(session, user_id, folder.id, new_parent_id)

    base_name = changes.get("base_name", folder.base_name)
    if base_name is None or not base_name.strip():
        raise ServiceError("Folder name cannot be empty")
    base_name = base_name.strip()
    _check_folder_name(session, user_id, new_parent_id, base_name, exclude_id=folder.id)

    requested_position = changes.get("position")
    if new_parent_id != old_parent_id:
        destination = _folder_siblings(session, user_id, new_parent_id)
        folder.parent_id = new_parent_id
        folder.position = max((item.position for item in destination), default=0) + 1
        folder.base_name = base_name
        session.flush()
        renumber_siblings(session, user_id, old_parent_id)
        destination.append(folder)
        if requested_position is not None:
            destination.remove(folder)
            destination.insert(min(requested_position - 1, len(destination)), folder)
        _set_folder_order(session, destination)
    else:
        folder.base_name = base_name
        if requested_position is not None:
            siblings = _folder_siblings(session, user_id, old_parent_id)
            siblings.remove(folder)
            siblings.insert(min(requested_position - 1, len(siblings)), folder)
            _set_folder_order(session, siblings)

    _record(
        session,
        user_id,
        "folder.update",
        folder_id=folder.id,
        from_parent_id=old_parent_id,
        to_parent_id=folder.parent_id,
    )
    session.flush()
    return folder


def delete_folder(session: Session, user_id: int, folder_id: int) -> None:
    folder = _require_folder(session, user_id, folder_id)
    has_child = session.scalar(select(Folder.id).where(Folder.parent_id == folder.id).limit(1))
    has_bookmark = session.scalar(
        select(Bookmark.id).where(Bookmark.folder_id == folder.id).limit(1)
    )
    if has_child is not None or has_bookmark is not None:
        raise Conflict("Only empty folders can be deleted")
    parent_id = folder.parent_id
    session.delete(folder)
    session.flush()
    renumber_siblings(session, user_id, parent_id)
    _record(session, user_id, "folder.delete", folder_id=folder_id, parent_id=parent_id)
    session.flush()


def _require_bookmark(session: Session, user_id: int, bookmark_id: int) -> Bookmark:
    bookmark = session.scalar(
        select(Bookmark).where(
            Bookmark.id == bookmark_id,
            Bookmark.user_id == user_id,
            Bookmark.deleted_at.is_(None),
        )
    )
    if bookmark is None:
        raise ResourceNotFound("Bookmark not found")
    return bookmark


def _duplicate_bookmark(
    session: Session, user_id: int, normalized_url: str, *, exclude_id: int | None = None
) -> Bookmark | None:
    statement = select(Bookmark).where(
        Bookmark.user_id == user_id,
        Bookmark.normalized_url == normalized_url,
        Bookmark.deleted_at.is_(None),
    )
    if exclude_id is not None:
        statement = statement.where(Bookmark.id != exclude_id)
    return session.scalar(statement)


def _next_bookmark_position(
    session: Session, folder_id: int, *, exclude_id: int | None = None
) -> int:
    statement = select(func.max(Bookmark.position)).where(
        Bookmark.folder_id == folder_id, Bookmark.deleted_at.is_(None)
    )
    if exclude_id is not None:
        statement = statement.where(Bookmark.id != exclude_id)
    return (session.scalar(statement) or 0) + 1


def create_bookmark(session: Session, user_id: int, data: BookmarkCreate) -> Bookmark:
    _require_folder(session, user_id, data.folder_id)
    normalized = normalize_url(data.url)
    existing = _duplicate_bookmark(session, user_id, normalized)
    if existing:
        raise DuplicateBookmark(existing.id)
    bookmark = Bookmark(
        user_id=user_id,
        title=data.title.strip(),
        url=data.url.strip(),
        normalized_url=normalized,
        folder_id=data.folder_id,
        notes=data.notes,
        position=data.position or _next_bookmark_position(session, data.folder_id),
    )
    session.add(bookmark)
    session.flush()
    _record(session, user_id, "bookmark.create", bookmark_id=bookmark.id, folder_id=bookmark.folder_id)
    session.flush()
    return bookmark


def update_bookmark(
    session: Session, user_id: int, bookmark_id: int, data: BookmarkUpdate
) -> Bookmark:
    bookmark = _require_bookmark(session, user_id, bookmark_id)
    changes = data.model_dump(exclude_unset=True)
    if "folder_id" in changes:
        if changes["folder_id"] is None:
            raise ServiceError("folder_id cannot be null")
        _require_folder(session, user_id, changes["folder_id"])
    if "url" in changes:
        normalized = normalize_url(changes["url"])
        existing = _duplicate_bookmark(
            session, user_id, normalized, exclude_id=bookmark.id
        )
        if existing:
            raise DuplicateBookmark(existing.id)
        bookmark.url = changes["url"].strip()
        bookmark.normalized_url = normalized
    if "title" in changes:
        if changes["title"] is None or not changes["title"].strip():
            raise ServiceError("Bookmark title cannot be empty")
        bookmark.title = changes["title"].strip()
    if "notes" in changes:
        bookmark.notes = changes["notes"] or ""
    if "folder_id" in changes:
        bookmark.folder_id = changes["folder_id"]
        if "position" not in changes:
            bookmark.position = _next_bookmark_position(
                session, bookmark.folder_id, exclude_id=bookmark.id
            )
    if "position" in changes:
        bookmark.position = changes["position"]
    _record(session, user_id, "bookmark.update", bookmark_id=bookmark.id, folder_id=bookmark.folder_id)
    session.flush()
    return bookmark


def delete_bookmark(session: Session, user_id: int, bookmark_id: int) -> None:
    bookmark = _require_bookmark(session, user_id, bookmark_id)
    bookmark.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    _record(session, user_id, "bookmark.delete", bookmark_id=bookmark.id, folder_id=bookmark.folder_id)
    session.flush()


def bookmark_domain(bookmark: Bookmark) -> str:
    try:
        return (urlsplit(bookmark.url).hostname or "").casefold()
    except ValueError:
        return ""


def bookmark_dict(bookmark: Bookmark) -> dict[str, object]:
    return {
        "id": bookmark.id,
        "folder_id": bookmark.folder_id,
        "title": bookmark.title,
        "url": bookmark.url,
        "normalized_url": bookmark.normalized_url,
        "notes": bookmark.notes,
        "position": bookmark.position,
        "domain": bookmark_domain(bookmark),
        "created_at": bookmark.created_at,
        "updated_at": bookmark.updated_at,
    }


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_bookmarks(
    session: Session,
    user_id: int,
    query: str,
    *,
    folder_id: int | None,
    limit: int,
    offset: int,
) -> tuple[list[Bookmark], int]:
    pattern = f"%{_escape_like(query.casefold())}%"
    predicates = [
        func.lower(Bookmark.title).like(pattern, escape="\\"),
        func.lower(Bookmark.url).like(pattern, escape="\\"),
        func.lower(Bookmark.notes).like(pattern, escape="\\"),
        func.lower(Folder.base_name).like(pattern, escape="\\"),
        # The normalized URL contains the computed host/domain and lets SQLite
        # evaluate this predicate without application-specific SQL functions.
        func.lower(Bookmark.normalized_url).like(pattern, escape="\\"),
    ]
    statement = (
        select(Bookmark)
        .join(Folder, Bookmark.folder_id == Folder.id)
        .where(
            Bookmark.user_id == user_id,
            Folder.user_id == user_id,
            Bookmark.deleted_at.is_(None),
            or_(*predicates),
        )
    )
    if folder_id is not None:
        statement = statement.where(Bookmark.folder_id == folder_id)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(
        session.scalars(
            statement.order_by(Bookmark.position, Bookmark.id).offset(offset).limit(limit)
        ).all()
    )
    return items, total
