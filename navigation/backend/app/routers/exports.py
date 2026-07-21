"""Authenticated audited export endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from app.dependencies import DatabaseSession, require_ready_user
from app.export_service import ExportAuditError, export_backup_json, export_bookmarks_html


from app.models import User


router = APIRouter(
    prefix="/exports", tags=["exports"], dependencies=[Depends(require_ready_user)]
)


def _audit_failure(error: ExportAuditError) -> None:
    raise HTTPException(409, {"message": "Export audit failed", "errors": error.errors})


@router.get("/bookmarks.html")
def bookmarks_html(
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
) -> Response:
    try:
        content = export_bookmarks_html(session, user.id)
    except ExportAuditError as error:
        _audit_failure(error)
    return Response(
        content,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bookmarks.html"'},
    )


@router.get("/backup.json")
def backup_json(
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
) -> JSONResponse:
    try:
        content = export_backup_json(session, user.id)
    except ExportAuditError as error:
        _audit_failure(error)
    return JSONResponse(
        content,
        headers={"Content-Disposition": 'attachment; filename="bookmarks-backup.json"'},
    )
