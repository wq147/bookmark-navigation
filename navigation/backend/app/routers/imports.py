"""Authenticated preview-first bookmark import endpoints."""

from __future__ import annotations

import os
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import DatabaseSession, require_csrf, require_ready_user
from app.backup_service import enforce_backup_retention
from app.import_service import (
    ConflictChoice,
    ImportErrorBase,
    apply_batch,
    create_preview,
    get_batch,
)
from app.models import ImportBatch, User


router = APIRouter(
    prefix="/imports", tags=["imports"], dependencies=[Depends(require_ready_user)]
)


class ApplyRequest(BaseModel):
    overrides: list[ConflictChoice] = Field(default_factory=list)


async def _read_html_upload(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "")
    boundary_match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type)
    if not content_type.casefold().startswith("multipart/form-data") or not boundary_match:
        raise HTTPException(415, "Expected one multipart HTML upload")
    boundary = (boundary_match.group(1) or boundary_match.group(2)).encode()
    max_bytes = int(os.getenv("NAV_IMPORT_MAX_BYTES", str(2 * 1024 * 1024)))
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes + 64 * 1024:
            raise HTTPException(413, "Import file is too large")

    file_parts: list[tuple[bytes, bytes]] = []
    for part in bytes(body).split(b"--" + boundary):
        if b"Content-Disposition:" not in part:
            continue
        headers, separator, payload = part.lstrip(b"\r\n").partition(b"\r\n\r\n")
        if not separator:
            continue
        disposition = next(
            (
                line
                for line in headers.split(b"\r\n")
                if line.lower().startswith(b"content-disposition:")
            ),
            b"",
        )
        if b'name="file"' not in disposition or b"filename=" not in disposition:
            continue
        file_parts.append((headers, payload.removesuffix(b"\r\n")))
    if len(file_parts) != 1:
        raise HTTPException(400, "Exactly one HTML file is required")
    headers, content = file_parts[0]
    if len(content) > max_bytes:
        raise HTTPException(413, "Import file is too large")
    parameterized_part_type = next(
        (
            line.partition(b":")[2].strip().lower()
            for line in headers.split(b"\r\n")
            if line.lower().startswith(b"content-type:")
        ),
        b"",
    )
    part_type = parameterized_part_type.split(b";", 1)[0].strip()
    beginning = content[:4096].lstrip().lower()
    looks_html = (
        beginning.startswith(b"<!doctype")
        or b"<html" in beginning
        or b"<dl" in beginning
    )
    if part_type not in {b"text/html", b"application/xhtml+xml"} or not looks_html:
        raise HTTPException(415, "Import file must be HTML")
    return content


def _raise_import_error(error: ImportErrorBase) -> None:
    raise HTTPException(error.status_code, error.detail) from error


@router.post("/preview", dependencies=[Depends(require_csrf)])
async def post_preview(
    request: Request,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
):
    content = await _read_html_upload(request)
    try:
        result = create_preview(session, user.id, content)
        session.commit()
        return result
    except ImportErrorBase as error:
        session.rollback()
        _raise_import_error(error)


@router.get("/{batch_id}")
def read_batch(
    batch_id: int,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
):
    try:
        return get_batch(session, user.id, batch_id)
    except ImportErrorBase as error:
        _raise_import_error(error)


@router.post("/{batch_id}/apply", dependencies=[Depends(require_csrf)])
def post_apply(
    batch_id: int,
    payload: ApplyRequest,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_ready_user)],
):
    batch = session.scalar(
        select(ImportBatch).where(
            ImportBatch.id == batch_id, ImportBatch.user_id == user.id
        )
    )
    if batch is None:
        raise HTTPException(404, "Import batch not found")
    try:
        result = apply_batch(session, user.id, batch, payload.overrides)
        session.commit()
        enforce_backup_retention(session)
        return result
    except ImportErrorBase as error:
        session.rollback()
        _raise_import_error(error)
    except Exception:
        session.rollback()
        raise
