"""Single-administrator account lifecycle and audit endpoints."""

from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.backup_service import create_backup, enforce_backup_retention
from app.dependencies import DatabaseSession, require_admin, require_csrf
from app.models import AdminAudit, SessionToken, User
from app.schemas import (
    AdminAuditResponse,
    AdminPasswordReset,
    AdminUserCreate,
    AdminUserResponse,
    AdminUserStatusUpdate,
)
from app.security import hash_password


router = APIRouter(
    prefix="/admin",
    tags=["administration"],
    dependencies=[Depends(require_admin)],
)


def _normalize_username(username: str) -> str:
    normalized = username.strip().casefold()
    if not normalized:
        raise HTTPException(422, "Username cannot be empty")
    return normalized


def _validate_password(username: str, password: str) -> None:
    if password.casefold() == username.casefold():
        raise HTTPException(422, "Password cannot match the username")


def _target(session: DatabaseSession, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


def _protect_primary_admin(user: User) -> None:
    if user.is_admin:
        raise HTTPException(409, "The primary administrator cannot be changed")


def _audit(session: DatabaseSession, actor: User, target: User, action: str) -> None:
    session.add(
        AdminAudit(
            actor_user_id=actor.id,
            target_user_id=target.id,
            target_username=target.username,
            action=action,
            result="success",
        )
    )


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(session: DatabaseSession) -> list[User]:
    return list(session.scalars(select(User).order_by(User.created_at, User.id)).all())


@router.post(
    "/users",
    response_model=AdminUserResponse,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def create_user(
    payload: AdminUserCreate,
    session: DatabaseSession,
    actor: Annotated[User, Depends(require_admin)],
) -> User:
    username = _normalize_username(payload.username)
    _validate_password(username, payload.temporary_password)
    user = User(
        username=username,
        password_hash=hash_password(payload.temporary_password),
        is_admin=False,
        is_active=True,
        must_change_password=True,
    )
    session.add(user)
    try:
        session.flush()
        _audit(session, actor, user, "user.create")
        session.commit()
        session.refresh(user)
        return user
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Username already exists") from error


@router.patch(
    "/users/{user_id}/status",
    response_model=AdminUserResponse,
    dependencies=[Depends(require_csrf)],
)
def update_status(
    user_id: int,
    payload: AdminUserStatusUpdate,
    session: DatabaseSession,
    actor: Annotated[User, Depends(require_admin)],
) -> User:
    target = _target(session, user_id)
    _protect_primary_admin(target)
    target.is_active = payload.is_active
    if not payload.is_active:
        session.execute(delete(SessionToken).where(SessionToken.user_id == target.id))
    _audit(session, actor, target, "user.enable" if payload.is_active else "user.disable")
    session.commit()
    session.refresh(target)
    return target


@router.post(
    "/users/{user_id}/reset-password",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def reset_password(
    user_id: int,
    payload: AdminPasswordReset,
    session: DatabaseSession,
    actor: Annotated[User, Depends(require_admin)],
) -> None:
    target = _target(session, user_id)
    _protect_primary_admin(target)
    _validate_password(target.username, payload.temporary_password)
    target.password_hash = hash_password(payload.temporary_password)
    target.must_change_password = True
    session.execute(delete(SessionToken).where(SessionToken.user_id == target.id))
    _audit(session, actor, target, "user.reset_password")
    session.commit()


@router.delete(
    "/users/{user_id}", status_code=204, dependencies=[Depends(require_csrf)]
)
def delete_user(
    user_id: int,
    session: DatabaseSession,
    actor: Annotated[User, Depends(require_admin)],
    confirmation: str | None = Header(None, alias="X-Confirm-Username"),
) -> Response:
    target = _target(session, user_id)
    _protect_primary_admin(target)
    decoded = unquote(confirmation or "")
    if decoded != target.username:
        raise HTTPException(400, "X-Confirm-Username must exactly match the username")
    backup = create_backup(session, reason=f"before-user-delete:{target.id}")
    try:
        _audit(session, actor, target, "user.delete")
        session.flush()
        session.delete(target)
        session.commit()
        enforce_backup_retention(session)
        return Response(status_code=204)
    except Exception:
        session.rollback()
        Path(backup.path).unlink(missing_ok=True)
        raise


@router.get("/audit", response_model=list[AdminAuditResponse])
def list_audit(
    session: DatabaseSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AdminAudit]:
    return list(
        session.scalars(
            select(AdminAudit)
            .order_by(AdminAudit.created_at.desc(), AdminAudit.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
