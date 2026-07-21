"""Authenticated snapshot discovery and recovery endpoints."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.backup_service import (
    BackupError,
    enforce_backup_retention,
    list_backups,
    restore_backup,
)
from app.dependencies import DatabaseSession, require_admin, require_csrf
from app.models import Backup, User


router = APIRouter(
    prefix="/backups", tags=["backups"], dependencies=[Depends(require_admin)]
)


def _item(backup: Backup) -> dict[str, object]:
    return {
        "id": backup.id,
        "filename": Path(backup.path).name,
        "checksum": backup.checksum,
        "created_at": backup.created_at,
    }


@router.get("")
def get_backups(session: DatabaseSession) -> list[dict[str, object]]:
    return [_item(backup) for backup in list_backups(session)]


@router.post("/{backup_id}/restore", dependencies=[Depends(require_csrf)])
def post_restore(
    backup_id: int,
    session: DatabaseSession,
    actor: Annotated[User, Depends(require_admin)],
    confirmation: str | None = Header(None, alias="X-Confirm-Restore"),
) -> dict[str, int]:
    if confirmation != "RESTORE ALL USERS":
        raise HTTPException(
            400, "X-Confirm-Restore must exactly equal RESTORE ALL USERS"
        )
    backup = session.get(Backup, backup_id)
    if backup is None:
        raise HTTPException(404, "Backup not found")
    try:
        pre_restore_backup_id = restore_backup(session, backup, actor.username)
        enforce_backup_retention(session)
        return {"pre_restore_backup_id": pre_restore_backup_id}
    except BackupError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
