"""Preview-first Netscape HTML import and explicit conflict merging."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backup_service import create_backup
from app.bookmark_domain import BookmarkRecord, FolderNode, normalize_url, parse_html
from app.bookmark_service import renumber_siblings
from app.models import Bookmark, Folder, ImportBatch, ImportItem


NUMBER_PREFIX_RE = re.compile(r"^(\d{1,3})[_\-\s、.]+(.+)$")
DEFAULT_BATCH_TTL_SECONDS = 24 * 60 * 60


class ImportErrorBase(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ImportNotFound(ImportErrorBase):
    status_code = 404


class ImportStateError(ImportErrorBase):
    status_code = 409


class ConflictChoice(BaseModel):
    item_id: int
    overwrite_title: bool = False
    overwrite_folder: bool = False
    overwrite_notes: bool = False


class ImportPreview(BaseModel):
    id: int
    status: str
    expires_at: datetime
    summary: dict[str, int]
    items: list[dict[str, object]]


class ApplyResult(BaseModel):
    batch_id: int
    status: str
    backup_id: int
    unique_bookmarks: int
    duplicate_urls: int
    unclassified: int
    created: list[dict[str, object]]
    updated: list[int]


def policy_path() -> Path:
    configured = os.getenv("NAV_BOOKMARK_POLICY_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).parents[3] / "bookmark_policy.json"


def load_policy() -> dict:
    return json.loads(policy_path().read_text(encoding="utf-8"))


def _strip_number_prefix(name: str) -> str:
    match = NUMBER_PREFIX_RE.match(name)
    return match.group(2) if match else name


def _canonical_path(path: tuple[str, ...], top_level_order: list[str]) -> tuple[str, ...]:
    return tuple(
        name if index == 0 and name in top_level_order else _strip_number_prefix(name)
        for index, name in enumerate(path)
    )


def _path_startswith(path: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return len(path) >= len(prefix) and path[: len(prefix)] == prefix


def _folder_attrs_by_canonical_path(tree, policy: dict) -> dict[tuple[str, ...], dict]:
    attrs: dict[tuple[str, ...], dict] = {}

    def walk(folder: FolderNode, path: tuple[str, ...]) -> None:
        for child in folder.children:
            if not isinstance(child, FolderNode):
                continue
            child_path = path + (child.title,)
            canonical = _canonical_path(child_path, policy.get("top_level_order", []))
            attrs[canonical] = dict(child.attrs)
            walk(child, child_path)

    walk(tree.root, ())
    return attrs


def _folder_manifest(tree, policy: dict) -> dict[str, object]:
    folders: list[dict[str, object]] = []

    def walk(folder: FolderNode, path: tuple[str, ...]) -> bool:
        contains_bookmark = False
        for child in folder.children:
            if isinstance(child, FolderNode):
                child_path = path + (child.title,)
                child_contains_bookmark = walk(child, child_path)
                contains_bookmark = contains_bookmark or child_contains_bookmark
                folders.append(
                    {
                        "path": list(
                            _canonical_path(
                                child_path, policy.get("top_level_order", [])
                            )
                        ),
                        "attrs": dict(child.attrs),
                        "empty_subtree": not child_contains_bookmark,
                    }
                )
            else:
                contains_bookmark = True
        return contains_bookmark

    walk(tree.root, ())
    return {"folders": folders, "toolbar_attrs": dict(tree.root.attrs)}


def _matches_title_rule(record: BookmarkRecord, canonical: tuple[str, ...], rule: dict) -> bool:
    text = f"{record.title}\n{record.url}".casefold()
    old_prefix = tuple(rule.get("old_path_prefix", []))
    if old_prefix and not _path_startswith(canonical, old_prefix):
        return False
    any_terms = [str(term).casefold() for term in rule.get("contains_any", [])]
    all_terms = [str(term).casefold() for term in rule.get("contains_all", [])]
    none_terms = [str(term).casefold() for term in rule.get("contains_none", [])]
    if any_terms and not any(term in text for term in any_terms):
        return False
    if all_terms and not all(term in text for term in all_terms):
        return False
    if none_terms and any(term in text for term in none_terms):
        return False
    return bool(any_terms or all_terms or old_prefix)


def classify_record(record: BookmarkRecord, policy: dict) -> tuple[tuple[str, ...], str]:
    classification = policy.get("classification", {})
    normalized = normalize_url(record.url)
    exact = {
        normalize_url(url): tuple(path)
        for url, path in classification.get("exact_url_overrides", {}).items()
    }
    if normalized in exact:
        return exact[normalized], "exact_url_override"

    canonical = _canonical_path(record.path, policy.get("top_level_order", []))
    for rule in classification.get("title_rules", []):
        if _matches_title_rule(record, canonical, rule):
            return tuple(rule["path"]), "title_rule"

    fallback = {
        tuple(key.split(" / ")): tuple(value)
        for key, value in classification.get("fallback_path_map", {}).items()
    }
    matches = [prefix for prefix in fallback if _path_startswith(canonical, prefix)]
    if matches:
        prefix = max(matches, key=len)
        return fallback[prefix] + canonical[len(prefix) :], "fallback_path"
    return ("00_待整理",), "unclassified"


def _folder_path(session: Session, user_id: int, folder_id: int) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[int] = set()
    while folder_id is not None:
        if folder_id in seen:
            raise ImportStateError("Folder tree contains a cycle")
        seen.add(folder_id)
        folder = session.scalar(
            select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
        )
        if folder is None:
            raise ImportStateError("Bookmark references a missing folder")
        names.append(folder.base_name)
        folder_id = folder.parent_id
    return tuple(reversed(names))


def _item_status(
    session: Session,
    user_id: int,
    record: BookmarkRecord,
    normalized: str,
    path: tuple[str, ...],
    method: str,
    seen_upload: set[str],
) -> tuple[str, Bookmark | None]:
    if normalized in seen_upload:
        return "duplicate", None
    seen_upload.add(normalized)
    existing = session.scalar(
        select(Bookmark).where(
            Bookmark.user_id == user_id,
            Bookmark.normalized_url == normalized, Bookmark.deleted_at.is_(None)
        )
    )
    if existing is None:
        return "new", None
    existing_path = _folder_path(session, user_id, existing.folder_id)
    imported_notes = record.notes or record.attrs.get("description", "")
    if existing.title != record.title or (imported_notes and existing.notes != imported_notes):
        return "conflict", existing
    if existing_path != path:
        return "suggested_move", existing
    return "duplicate", existing


def create_preview(session: Session, user_id: int, content: bytes) -> ImportPreview:
    try:
        tree = parse_html(content.decode("utf-8-sig", errors="replace"))
    except Exception as error:
        raise ImportErrorBase("Unable to parse Netscape bookmark HTML") from error
    records = tree.bookmarks()
    if not records:
        raise ImportErrorBase("Bookmark HTML contains no bookmarks")
    policy = load_policy()
    source_folder_attrs = _folder_attrs_by_canonical_path(tree, policy)
    ttl = int(os.getenv("NAV_IMPORT_BATCH_TTL_SECONDS", str(DEFAULT_BATCH_TTL_SECONDS)))
    batch = ImportBatch(
        user_id=user_id,
        source_name=f"sha256:{hashlib.sha256(content).hexdigest()}",
        status="previewed",
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=ttl),
        folder_manifest=_folder_manifest(tree, policy),
    )
    session.add(batch)
    session.flush()

    seen_upload: set[str] = set()
    for record in records:
        normalized = normalize_url(record.url)
        if not normalized:
            continue
        path, method = classify_record(record, policy)
        status, existing = _item_status(
            session, user_id, record, normalized, path, method, seen_upload
        )
        session.add(
            ImportItem(
                batch_id=batch.id,
                bookmark_id=existing.id if existing else None,
                source_url=record.url.strip(),
                title=record.title.strip() or record.url.strip(),
                notes=record.notes or record.attrs.get("description", ""),
                normalized_url=normalized,
                folder_path=json.dumps(path, ensure_ascii=False),
                classification_method=method,
                attrs=dict(record.attrs),
                folder_attrs=[
                    source_folder_attrs.get(path[:depth], {})
                    for depth in range(1, len(path) + 1)
                ],
                toolbar_attrs=dict(tree.root.attrs),
                status=status,
            )
        )
    session.flush()
    return preview_dict(session, batch)


def _items(session: Session, batch_id: int) -> list[ImportItem]:
    return list(
        session.scalars(
            select(ImportItem).where(ImportItem.batch_id == batch_id).order_by(ImportItem.id)
        ).all()
    )


def _summary(items: list[ImportItem]) -> dict[str, int]:
    summary = {
        name: sum(item.status == name for item in items)
        for name in ("new", "duplicate", "conflict", "suggested_move")
    }
    summary["unclassified"] = sum(
        item.classification_method == "unclassified" for item in items
    )
    return summary


def _item_dict(item: ImportItem) -> dict[str, object]:
    return {
        "id": item.id,
        "source_url": item.source_url,
        "title": item.title,
        "notes": item.notes,
        "folder_path": json.loads(item.folder_path),
        "classification_method": item.classification_method,
        "attrs": item.attrs,
        "folder_attrs": item.folder_attrs,
        "toolbar_attrs": item.toolbar_attrs,
        "status": item.status,
        "bookmark_id": item.bookmark_id,
    }


def preview_dict(session: Session, batch: ImportBatch) -> ImportPreview:
    items = _items(session, batch.id)
    return ImportPreview(
        id=batch.id,
        status=batch.status,
        expires_at=batch.expires_at,
        summary=_summary(items),
        items=[_item_dict(item) for item in items],
    )


def get_batch(session: Session, user_id: int, batch_id: int) -> ImportPreview:
    batch = session.scalar(
        select(ImportBatch).where(
            ImportBatch.id == batch_id, ImportBatch.user_id == user_id
        )
    )
    if batch is None:
        raise ImportNotFound("Import batch not found")
    return preview_dict(session, batch)


def _ensure_folder_path(
    session: Session,
    user_id: int,
    path: tuple[str, ...],
    folder_attrs: list[dict] | None = None,
    toolbar_attrs: dict | None = None,
) -> Folder:
    parent_id: int | None = None
    folder: Folder | None = None
    for depth, base_name in enumerate(path):
        clause = (
            Folder.parent_id.is_(None)
            if parent_id is None
            else Folder.parent_id == parent_id
        )
        folder = session.scalar(
            select(Folder).where(
                Folder.user_id == user_id, clause, Folder.base_name == base_name
            )
        )
        if folder is None:
            position = (
                session.scalar(
                    select(func.max(Folder.position)).where(
                        Folder.user_id == user_id, clause
                    )
                )
                or 0
            ) + 1
            attrs = (
                folder_attrs[depth]
                if folder_attrs is not None and depth < len(folder_attrs)
                else {}
            )
            folder = Folder(
                user_id=user_id,
                parent_id=parent_id,
                base_name=base_name,
                position=position,
                attrs=attrs,
                toolbar_attrs=(toolbar_attrs or {}) if parent_id is None else {},
            )
            session.add(folder)
            session.flush()
        elif parent_id is None and toolbar_attrs and not folder.toolbar_attrs:
            folder.toolbar_attrs = toolbar_attrs
        parent_id = folder.id
    if folder is None:
        raise ImportStateError("Import item has an empty folder path")
    return folder


def _renumber_all_folders(session: Session, user_id: int, policy: dict) -> None:
    parent_ids = [None]
    parent_ids.extend(
        session.scalars(
            select(Folder.id).where(Folder.user_id == user_id).order_by(Folder.id)
        ).all()
    )
    for parent_id in parent_ids:
        renumber_siblings(session, user_id, parent_id)
        clause = (
            Folder.parent_id.is_(None)
            if parent_id is None
            else Folder.parent_id == parent_id
        )
        siblings = list(
            session.scalars(
                select(Folder)
                .where(Folder.user_id == user_id, clause)
                .order_by(Folder.position)
            ).all()
        )
        if not siblings:
            continue
        if parent_id is None:
            preferred = policy.get("top_level_order", [])
        else:
            preferred = policy.get("child_order", {}).get(
                " / ".join(_folder_path(session, user_id, parent_id)), []
            )
        rank = {name: index for index, name in enumerate(preferred)}
        ordered = sorted(
            enumerate(siblings),
            key=lambda entry: (rank.get(entry[1].base_name, len(rank)), entry[0]),
        )
        for temporary, (_, folder) in enumerate(ordered, 1):
            folder.position = -temporary
        session.flush()
        for position, (_, folder) in enumerate(ordered, 1):
            folder.position = position
        session.flush()


def _assert_tree_is_valid(session: Session, user_id: int) -> None:
    for folder in session.scalars(
        select(Folder).where(Folder.user_id == user_id)
    ).all():
        seen = {folder.id}
        parent_id = folder.parent_id
        while parent_id is not None:
            if parent_id in seen:
                raise ImportStateError("Folder tree contains a cycle")
            seen.add(parent_id)
            parent = session.scalar(
                select(Folder).where(Folder.id == parent_id, Folder.user_id == user_id)
            )
            if parent is None:
                raise ImportStateError("Folder tree contains a missing parent")
            parent_id = parent.parent_id


def apply_batch(
    session: Session, user_id: int, batch: ImportBatch, choices: list[ConflictChoice]
) -> ApplyResult:
    if batch.user_id != user_id:
        raise ImportNotFound("Import batch not found")
    now = datetime.now(UTC).replace(tzinfo=None)
    if batch.status != "previewed":
        raise ImportStateError(f"Import batch is {batch.status}")
    if batch.expires_at <= now:
        raise ImportStateError("Import batch has expired")
    items = _items(session, batch.id)
    item_ids = {item.id for item in items}
    choice_ids = [choice.item_id for choice in choices]
    if len(choice_ids) != len(set(choice_ids)) or any(
        item_id not in item_ids for item_id in choice_ids
    ):
        raise ImportErrorBase("Each override must reference one item in this batch")
    choice_map = {choice.item_id: choice for choice in choices}
    eligible_override_ids = {
        item.id for item in items if item.status in {"conflict", "suggested_move"}
    }
    if any(choice.item_id not in eligible_override_ids for choice in choices):
        raise ImportErrorBase("Overrides are only allowed for conflict items")

    for item in items:
        if item.bookmark_id is not None:
            current = session.scalar(
                select(Bookmark).where(
                    Bookmark.id == item.bookmark_id, Bookmark.user_id == user_id
                )
            )
            if (
                current is None
                or current.deleted_at is not None
                or current.normalized_url != item.normalized_url
            ):
                raise ImportStateError("Import preview is stale")
        elif item.status != "duplicate":
            concurrent = session.scalar(
                select(Bookmark.id).where(
                    Bookmark.user_id == user_id,
                    Bookmark.normalized_url == item.normalized_url,
                    Bookmark.deleted_at.is_(None),
                )
            )
            if concurrent is not None:
                raise ImportStateError("Import preview is stale")

    backup = create_backup(session, reason=f"before-import:{batch.id}")
    created: list[dict[str, object]] = []
    updated: list[int] = []
    unique_bookmarks = 0
    duplicate_urls = 0
    unclassified = 0
    try:
        with session.begin_nested():
            manifest = batch.folder_manifest or {}
            empty_folders = manifest.get("folders", [])
            empty_attrs = {
                tuple(entry["path"]): entry.get("attrs", {})
                for entry in empty_folders
            }
            for entry in sorted(
                (entry for entry in empty_folders if entry.get("empty_subtree")),
                key=lambda item: len(item["path"]),
            ):
                path = tuple(entry["path"])
                _ensure_folder_path(
                    session,
                    user_id,
                    path,
                    [empty_attrs.get(path[:depth], {}) for depth in range(1, len(path) + 1)],
                    manifest.get("toolbar_attrs", {}),
                )
            for item in items:
                if item.status == "duplicate":
                    duplicate_urls += 1
                    continue
                path = tuple(json.loads(item.folder_path))
                if item.bookmark_id is None:
                    folder = _ensure_folder_path(
                        session, user_id, path, item.folder_attrs, item.toolbar_attrs
                    )
                    bookmark = Bookmark(
                        user_id=user_id,
                        folder_id=folder.id,
                        title=item.title,
                        url=item.source_url,
                        normalized_url=item.normalized_url,
                        notes=item.notes,
                        attrs=item.attrs,
                        position=(
                            session.scalar(
                                select(func.max(Bookmark.position)).where(
                                    Bookmark.folder_id == folder.id,
                                    Bookmark.deleted_at.is_(None),
                                )
                            )
                            or 0
                        )
                        + 1,
                    )
                    session.add(bookmark)
                    session.flush()
                    item.bookmark_id = bookmark.id
                    created.append({"id": bookmark.id, "folder_path": list(path)})
                    unique_bookmarks += 1
                    unclassified += item.classification_method == "unclassified"
                    continue

                bookmark = session.scalar(
                    select(Bookmark).where(
                        Bookmark.id == item.bookmark_id, Bookmark.user_id == user_id
                    )
                )
                unique_bookmarks += 1
                choice = choice_map.get(item.id)
                if choice is None:
                    continue
                changed = False
                if choice.overwrite_title:
                    bookmark.title = item.title
                    changed = True
                if choice.overwrite_notes:
                    bookmark.notes = item.notes
                    changed = True
                if choice.overwrite_folder:
                    bookmark.folder_id = _ensure_folder_path(
                        session, user_id, path, item.folder_attrs, item.toolbar_attrs
                    ).id
                    bookmark.position = (
                        session.scalar(
                            select(func.max(Bookmark.position)).where(
                                Bookmark.folder_id == bookmark.folder_id,
                                Bookmark.deleted_at.is_(None),
                                Bookmark.id != bookmark.id,
                            )
                        )
                        or 0
                    ) + 1
                    changed = True
                if changed:
                    updated.append(bookmark.id)

            _renumber_all_folders(session, user_id, load_policy())
            _assert_tree_is_valid(session, user_id)
            batch.status = "applied"
            batch.backup_id = backup.id
            session.flush()
    except Exception as error:
        Path(backup.path).unlink(missing_ok=True)
        if isinstance(error, IntegrityError):
            raise ImportStateError("Import preview is stale") from error
        raise

    return ApplyResult(
        batch_id=batch.id,
        status=batch.status,
        backup_id=backup.id,
        unique_bookmarks=unique_bookmarks,
        duplicate_urls=duplicate_urls,
        unclassified=unclassified,
        created=created,
        updated=updated,
    )
