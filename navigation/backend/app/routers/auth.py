"""Session authentication and self-service password endpoints."""

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select

from app.dependencies import DatabaseSession, require_csrf, require_session, require_user
from app.models import SessionToken, User
from app.schemas import ChangePasswordRequest, LoginRequest, LoginResponse, UserResponse
from app.security import LoginFailureLimiter, hash_password, new_session_tokens, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])
failure_limiter = LoginFailureLimiter()
SESSION_LIFETIME = timedelta(days=7)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> LoginResponse:
    client_ip = _client_ip(request)
    if failure_limiter.is_limited(payload.username, client_ip):
        raise HTTPException(429, "Too many login attempts")

    normalized = payload.username.strip().casefold()
    user = session.scalar(select(User).where(User.username == normalized))
    password_is_valid = verify_password(
        user.password_hash if user is not None else None,
        payload.password,
    )
    if user is None or not password_is_valid or not user.is_active:
        failure_limiter.record_failure(payload.username, client_ip)
        raise HTTPException(401, "Invalid username or password")

    failure_limiter.clear(payload.username, client_ip)
    raw, digest, csrf = new_session_tokens()
    session.add(
        SessionToken(
            user_id=user.id,
            token_hash=digest,
            csrf_token=csrf,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + SESSION_LIFETIME,
        )
    )
    session.commit()
    response.set_cookie(
        "navigation_session",
        raw,
        httponly=True,
        secure=os.getenv("NAV_TEST_MODE") != "1",
        samesite="strict",
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
    )
    return LoginResponse(csrf_token=csrf)


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(
    response: Response,
    session: DatabaseSession,
    token: Annotated[SessionToken, Depends(require_session)],
) -> None:
    session.delete(token)
    session.commit()
    response.delete_cookie("navigation_session", path="/", samesite="strict")


@router.get("/me", response_model=UserResponse)
def me(
    user: Annotated[User, Depends(require_user)],
    token: Annotated[SessionToken, Depends(require_session)],
) -> UserResponse:
    """Bootstrap both identity and the tab-scoped CSRF token from the session cookie."""

    return UserResponse(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        csrf_token=token.csrf_token,
    )


def _validate_new_password(user: User, password: str) -> None:
    if password.casefold() == user.username.casefold():
        raise HTTPException(422, "Password cannot match the username")


@router.post("/change-password", status_code=204, dependencies=[Depends(require_csrf)])
def change_password(
    payload: ChangePasswordRequest,
    session: DatabaseSession,
    user: Annotated[User, Depends(require_user)],
    token: Annotated[SessionToken, Depends(require_session)],
) -> None:
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(400, "Current password is incorrect")
    _validate_new_password(user, payload.new_password)
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    session.execute(
        delete(SessionToken).where(
            SessionToken.user_id == user.id, SessionToken.id != token.id
        )
    )
    session.commit()
