"""Authenticated folder management endpoints."""

import re
import secrets
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.bookmark_service import (
    ServiceError,
    create_folder,
    delete_folder,
    renumber_siblings,
    update_folder,
)
from app.backup_service import create_backup, enforce_backup_retention
from app.dependencies import DatabaseSession, require_csrf, require_ready_user
from app.models import Bookmark, Folder, User
from app.schemas import FolderCreate, FolderResponse, FolderUpdate


router = APIRouter(
    prefix="/folders",
    tags=["folders"],
    dependencies=[Depends(require_ready_user)],
)


def _decode_confirmation(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.isascii() or re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise HTTPException(400, "X-Confirm-Delete must be percent-encoded UTF-8")
    try:
        return unquote(value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise HTTPException(
            400, "X-Confirm-Delete must be percent-encoded UTF-8"
        ) from error


def _raise_service_error(error: ServiceError) -> None:
    raise HTTPException(error.status_code, error.detail) from error


def _folder_response(
    session: DatabaseSession, user_id: int, folder: Folder
) -> dict[str, object]:
    bookmark_count = session.scalar(
        select(func.count(Bookmark.id)).where(
            Bookmark.user_id == user_id,
            Bookmark.folder_id == folder.id,
            Bookmark.deleted_at.is_(None),
        )
    ) or 0
    return {
        "id": folder.id,
        "parent_id": folder.parent_id,
        "base_name": folder.base_name,
        "position": folder.position,
        "bookmark_count": bookmark_count,
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
    }


@router.get("", response_model=list[FolderResponse])
def list_folders(
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
) -> list[dict[str, object]]:
    """Return folders with direct (non-recursive), active bookmark counts."""

    count = func.count(Bookmark.id).filter(Bookmark.deleted_at.is_(None))
    rows = session.execute(
        select(Folder, count.label("bookmark_count"))
        .outerjoin(
            Bookmark,
            (Bookmark.folder_id == Folder.id) & (Bookmark.user_id == user.id),
        )
        .where(Folder.user_id == user.id)
        .group_by(Folder.id)
        .order_by(Folder.parent_id, Folder.position, Folder.id)
    ).all()
    return [
        {
            "id": folder.id,
            "parent_id": folder.parent_id,
            "base_name": folder.base_name,
            "position": folder.position,
            "bookmark_count": bookmark_count,
            "created_at": folder.created_at,
            "updated_at": folder.updated_at,
        }
        for folder, bookmark_count in rows
    ]


@router.get("/{folder_id}", response_model=FolderResponse)
def get_folder(
    folder_id: int,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
) -> dict[str, object]:
    folder = session.scalar(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id)
    )
    if folder is None:
        raise HTTPException(404, "Folder not found")
    return _folder_response(session, user.id, folder)


@router.post(
    "",
    response_model=FolderResponse,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def post_folder(
    payload: FolderCreate,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
) -> dict[str, object]:
    try:
        folder = create_folder(session, user.id, payload)
        session.commit()
        session.refresh(folder)
        return _folder_response(session, user.id, folder)
    except ServiceError as error:
        session.rollback()
        _raise_service_error(error)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Folder conflicts with an existing sibling") from error


@router.patch(
    "/{folder_id}",
    response_model=FolderResponse,
    dependencies=[Depends(require_csrf)],
)
def patch_folder(
    folder_id: int,
    payload: FolderUpdate,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
) -> dict[str, object]:
    try:
        folder = update_folder(session, user.id, folder_id, payload)
        session.commit()
        session.refresh(folder)
        return _folder_response(session, user.id, folder)
    except ServiceError as error:
        session.rollback()
        _raise_service_error(error)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Folder conflicts with an existing sibling") from error


@router.delete("/{folder_id}", dependencies=[Depends(require_csrf)])
def remove_folder(
    folder_id: int,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
    recursive: bool = False,
    confirmation: str | None = Header(None, alias="X-Confirm-Delete"),
):
    backup = None
    try:
        if recursive:
            folder = session.scalar(
                select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id)
            )
            if folder is None:
                raise HTTPException(404, "Folder not found")
            decoded_confirmation = _decode_confirmation(confirmation)
            confirmed = decoded_confirmation is not None and secrets.compare_digest(
                decoded_confirmation.encode("utf-8"), folder.base_name.encode("utf-8")
            )
            if not confirmed:
                raise HTTPException(400, "X-Confirm-Delete must exactly match the folder name")
            backup = create_backup(session, f"before-recursive-folder-delete:{folder_id}")
            parent_id = folder.parent_id
            session.delete(folder)
            session.flush()
            renumber_siblings(session, user.id, parent_id)
            session.commit()
            enforce_backup_retention(session)
            return {"backup_id": backup.id}
        delete_folder(session, user.id, folder_id)
        session.commit()
        return Response(status_code=204)
    except ServiceError as error:
        session.rollback()
        if backup is not None:
            Path(backup.path).unlink(missing_ok=True)
        _raise_service_error(error)
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        if backup is not None:
            Path(backup.path).unlink(missing_ok=True)
        raise
