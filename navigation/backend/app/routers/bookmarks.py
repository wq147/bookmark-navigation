"""Authenticated bookmark CRUD and per-user search endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.bookmark_domain import normalize_url
from app.bookmark_service import (
    DuplicateBookmark,
    ServiceError,
    bookmark_dict,
    create_bookmark,
    delete_bookmark,
    search_bookmarks,
    update_bookmark,
)
from app.dependencies import DatabaseSession, require_csrf, require_ready_user
from app.models import Bookmark, Folder, User
from app.schemas import BookmarkCreate, BookmarkResponse, BookmarkUpdate, SearchResponse


router = APIRouter(tags=["bookmarks"], dependencies=[Depends(require_ready_user)])


def _require_owned_folder(
    session: DatabaseSession, user_id: int, folder_id: int | None
) -> None:
    if folder_id is None:
        return
    if session.scalar(
        select(Folder.id).where(Folder.id == folder_id, Folder.user_id == user_id)
    ) is None:
        raise HTTPException(404, "Folder not found")


def _error_response(error: ServiceError):
    if isinstance(error, DuplicateBookmark):
        return JSONResponse(
            status_code=409,
            content={"detail": error.detail, "existing_id": error.existing_id},
        )
    raise HTTPException(error.status_code, error.detail) from error


def _bookmark_integrity_response(session: DatabaseSession, user_id: int, url: str):
    session.rollback()
    normalized = normalize_url(url)
    existing = session.scalar(
        select(Bookmark).where(
            Bookmark.user_id == user_id,
            Bookmark.normalized_url == normalized,
            Bookmark.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return _error_response(DuplicateBookmark(existing.id))
    raise HTTPException(409, "Bookmark conflicts with existing data")


@router.get("/bookmarks", response_model=list[BookmarkResponse])
def list_bookmarks(
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
    folder_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, object]]:
    _require_owned_folder(session, user.id, folder_id)
    statement = select(Bookmark).where(
        Bookmark.user_id == user.id, Bookmark.deleted_at.is_(None)
    )
    if folder_id is not None:
        statement = statement.where(Bookmark.folder_id == folder_id)
    bookmarks = session.scalars(
        statement.order_by(Bookmark.position, Bookmark.id).offset(offset).limit(limit)
    ).all()
    return [bookmark_dict(bookmark) for bookmark in bookmarks]


@router.get("/bookmarks/{bookmark_id}", response_model=BookmarkResponse)
def get_bookmark(
    bookmark_id: int,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
) -> dict[str, object]:
    bookmark = session.scalar(
        select(Bookmark).where(
            Bookmark.id == bookmark_id,
            Bookmark.user_id == user.id,
            Bookmark.deleted_at.is_(None),
        )
    )
    if bookmark is None:
        raise HTTPException(404, "Bookmark not found")
    return bookmark_dict(bookmark)


@router.post(
    "/bookmarks",
    response_model=BookmarkResponse,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def post_bookmark(
    payload: BookmarkCreate,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
):
    user_id = user.id
    try:
        bookmark = create_bookmark(session, user_id, payload)
        session.commit()
        session.refresh(bookmark)
        return bookmark_dict(bookmark)
    except ServiceError as error:
        session.rollback()
        return _error_response(error)
    except IntegrityError:
        return _bookmark_integrity_response(session, user_id, payload.url)


@router.patch(
    "/bookmarks/{bookmark_id}",
    response_model=BookmarkResponse,
    dependencies=[Depends(require_csrf)],
)
def patch_bookmark(
    bookmark_id: int,
    payload: BookmarkUpdate,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
):
    user_id = user.id
    try:
        bookmark = update_bookmark(session, user_id, bookmark_id, payload)
        session.commit()
        session.refresh(bookmark)
        return bookmark_dict(bookmark)
    except ServiceError as error:
        session.rollback()
        return _error_response(error)
    except IntegrityError:
        return _bookmark_integrity_response(session, user_id, payload.url or "")


@router.delete(
    "/bookmarks/{bookmark_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def remove_bookmark(
    bookmark_id: int,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
) -> None:
    try:
        delete_bookmark(session, user.id, bookmark_id)
        session.commit()
    except ServiceError as error:
        session.rollback()
        _error_response(error)


@router.get("/search", response_model=SearchResponse)
def search(
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
    q: str = "",
    folder_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    _require_owned_folder(session, user.id, folder_id)
    items, total = search_bookmarks(
        session,
        user.id,
        q,
        folder_id=folder_id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [bookmark_dict(bookmark) for bookmark in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
