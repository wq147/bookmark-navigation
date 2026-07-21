"""ASGI application and command-line entry point."""

import argparse
import getpass
import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import func, select

from app.config import APP_NAME
from app.db import SessionLocal
from app.dependencies import require_user
from app.models import User
from app.routers.auth import router as auth_router
from app.routers.admin import router as admin_router
from app.routers.backups import router as backups_router
from app.routers.bookmarks import router as bookmarks_router
from app.routers.exports import router as exports_router
from app.routers.folders import router as folders_router
from app.routers.imports import router as imports_router
from app.security import hash_password

app = FastAPI(title=APP_NAME)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(folders_router, prefix="/api/v1")
app.include_router(bookmarks_router, prefix="/api/v1")
app.include_router(imports_router, prefix="/api/v1")
app.include_router(exports_router, prefix="/api/v1")
app.include_router(backups_router, prefix="/api/v1")

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@app.exception_handler(HTTPException)
async def redirect_unauthenticated_spa(
    request: Request,
    exc: HTTPException,
) -> Response:
    if exc.status_code == 401 and not request.url.path.startswith("/api/"):
        return RedirectResponse("/login", status_code=303)
    return await http_exception_handler(request, exc)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _static_file(relative_path: str) -> FileResponse:
    static_root = STATIC_DIR.resolve()
    candidate = (static_root / relative_path).resolve()
    if static_root not in candidate.parents or not candidate.is_file():
        raise HTTPException(404)
    return FileResponse(candidate)


@app.get("/login", include_in_schema=False)
def login_spa() -> FileResponse:
    return _static_file("index.html")


@app.get("/assets/{asset_path:path}", include_in_schema=False)
def static_asset(asset_path: str) -> FileResponse:
    return _static_file(f"assets/{asset_path}")


@app.get("/{spa_path:path}", include_in_schema=False)
def authenticated_spa(
    spa_path: str,
    _user: Annotated[User, Depends(require_user)],
) -> FileResponse:
    if spa_path.startswith("api/") or spa_path == "api":
        raise HTTPException(404)
    return _static_file("index.html")


def create_user(username: str) -> None:
    normalized = username.strip().casefold()
    if not normalized:
        raise SystemExit("Username cannot be empty")
    password_file = os.getenv("NAV_INITIAL_PASSWORD_FILE")
    password = (
        Path(password_file).read_text().rstrip("\r\n")
        if password_file
        else getpass.getpass()
    )
    if not password:
        raise SystemExit("Password cannot be empty")
    if len(password) < 12:
        raise SystemExit("Initial password must contain at least 12 characters")
    if password.casefold() == normalized:
        raise SystemExit("Initial password cannot match the username")
    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(User)):
            raise SystemExit("A user already exists")
        session.add(
            User(
                username=normalized,
                password_hash=hash_password(password),
                is_admin=True,
                is_active=True,
                must_change_password=True,
            )
        )
        session.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user")
    create.add_argument("--username", required=True)
    args = parser.parse_args()
    if args.command == "create-user":
        create_user(args.username)


if __name__ == "__main__":
    main()
