"""Authentication dependencies shared by protected routes."""

import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import SessionToken, User
from app.security import digest_session_token

DatabaseSession = Annotated[Session, Depends(get_session)]


def require_session(
    request: Request,
    session: DatabaseSession,
) -> SessionToken:
    navigation_session = request.cookies.get("navigation_session")
    if not navigation_session:
        raise HTTPException(401, "Authentication required")
    digest = digest_session_token(navigation_session)
    token = session.scalar(select(SessionToken).where(SessionToken.token_hash == digest))
    now = datetime.now(UTC).replace(tzinfo=None)
    if token is None or token.expires_at <= now:
        if token is not None:
            session.delete(token)
            session.commit()
        raise HTTPException(401, "Authentication required")
    return token


def require_user(
    request: Request,
    session: DatabaseSession,
) -> User:
    token = require_session(request, session)
    user = session.get(User, token.user_id)
    if user is None or not user.is_active:
        if token is not None:
            session.delete(token)
            session.commit()
        raise HTTPException(401, "Authentication required")
    return user


def require_ready_user(
    user: Annotated[User, Depends(require_user)],
) -> User:
    if user.must_change_password:
        raise HTTPException(
            403,
            {
                "code": "PASSWORD_CHANGE_REQUIRED",
                "message": "Password must be changed before continuing",
            },
        )
    return user


def require_admin(
    user: Annotated[User, Depends(require_ready_user)],
) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Administrator access required")
    return user


def require_csrf(
    request: Request,
    token: Annotated[SessionToken, Depends(require_session)],
) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(supplied, token.csrf_token):
            raise HTTPException(403, "Invalid CSRF token")
