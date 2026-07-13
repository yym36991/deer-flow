"""Business integration API — JIT user provisioning + thread creation.

``POST /api/v1/integration/threads`` is the single entry point for external
systems that need per-employee DeerFlow sessions without manual registration.

There is intentionally no ``/integration/session`` endpoint: when the JWT
expires, callers re-invoke this route with ``username`` + ``password`` to
obtain a fresh token and a new thread (expired token = new session).

Session credentials (same as register/login):

- **Request**: ``Cookie: access_token=…``
- **Response** (password path): ``Set-Cookie: access_token=…``; CSRF middleware
  also sets ``Set-Cookie: csrf_token=…`` on successful POST (not in JSON body).
- **Response body**: ``ThreadResponse`` only — identical to ``POST /api/threads``.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import Field, field_validator

from app.gateway.auth import create_access_token, decode_token
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError, token_error_to_code
from app.gateway.deps import get_access_token_from_request, get_local_provider
from app.gateway.routers.auth import (
    _check_rate_limit,
    _get_client_ip,
    _record_login_failure,
    _record_login_success,
    _set_session_cookie,
    _validate_strong_password,
)
from app.gateway.routers.threads import ThreadCreateRequest, ThreadResponse, _strip_reserved_metadata, create_thread_for_user
from deerflow.runtime.user_context import reset_current_user, set_current_user

router = APIRouter(prefix="/api/v1/integration", tags=["integration"])

_INTEGRATION_EMAIL_DOMAIN = "@58.com"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class IntegrationThreadCreateRequest(ThreadCreateRequest):
    """Request body for ``POST /api/v1/integration/threads``.

    Authentication (one of):

    - ``username`` + ``password`` (both required) — JIT / new session
    - Valid ``access_token`` cookie — existing session

    When ``username`` + ``password`` are present, they take precedence over any
    request cookie and start a new session (fresh JWT + new thread).
    """

    username: str | None = Field(
        default=None,
        description="Corporate username without domain (maps to `{username}@58.com`). Required with password.",
    )
    password: str | None = Field(
        default=None,
        min_length=8,
        description="Integrator-managed DeerFlow password. Required with username. Min 8 chars, not a common password.",
    )

    _strong_password = field_validator("password")(classmethod(lambda cls, v: _validate_strong_password(v) if v is not None else v))


def _integration_email(username: str) -> str:
    return f"{username.strip().lower()}{_INTEGRATION_EMAIL_DOMAIN}"


def _validate_username(username: str) -> str:
    normalized = username.strip()
    if not normalized or "@" in normalized or not _USERNAME_RE.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthErrorResponse(
                code=AuthErrorCode.INVALID_CREDENTIALS,
                message="username must be a non-empty corporate id without '@'",
            ).model_dump(),
        )
    return normalized


async def _resolve_user_from_token(token: str):
    """Return User on success, TokenError on decode failure, or None when stale."""
    payload = decode_token(token)
    if isinstance(payload, TokenError):
        return payload

    provider = get_local_provider()
    user = await provider.get_user(payload.sub)
    if user is None:
        return None
    if user.token_version != payload.ver:
        return None
    return user


async def _authenticate_or_provision(username: str, password: str, client_ip: str):
    """JIT-create or verify a local user from corporate credentials."""
    from app.gateway.auth.models import User

    _check_rate_limit(client_ip)
    email = _integration_email(username)
    provider = get_local_provider()
    user = await provider.get_user_by_email(email)
    if user is None:
        try:
            user = await provider.create_user(email=email, password=password, system_role="user")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthErrorResponse(
                    code=AuthErrorCode.EMAIL_ALREADY_EXISTS,
                    message="Email already registered",
                ).model_dump(),
            )
        _record_login_success(client_ip)
        return user

    user = await provider.authenticate({"email": email, "password": password})
    if user is None:
        _record_login_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthErrorResponse(
                code=AuthErrorCode.INVALID_CREDENTIALS,
                message="Incorrect username or password",
            ).model_dump(),
        )
    _record_login_success(client_ip)
    return user


@router.post("/threads", response_model=ThreadResponse)
async def create_integration_thread(
    body: IntegrationThreadCreateRequest,
    request: Request,
    response: Response,
) -> ThreadResponse:
    """Create a thread for an integration caller (JIT user + session).

    Response body matches ``POST /api/threads`` (``ThreadResponse``).
    Session cookies (``access_token``, ``csrf_token``) are set via ``Set-Cookie``
    headers only — same pattern as ``POST /api/v1/auth/register``.
    """
    has_password_creds = body.username is not None and body.password is not None
    if body.username is not None and body.password is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthErrorResponse(
                code=AuthErrorCode.INVALID_CREDENTIALS,
                message="username and password must be provided together",
            ).model_dump(),
        )
    if body.password is not None and body.username is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthErrorResponse(
                code=AuthErrorCode.INVALID_CREDENTIALS,
                message="username and password must be provided together",
            ).model_dump(),
        )

    token_str = get_access_token_from_request(request)

    if has_password_creds:
        username = _validate_username(body.username)  # type: ignore[arg-type]
        client_ip = _get_client_ip(request)
        user = await _authenticate_or_provision(username, body.password, client_ip)  # type: ignore[arg-type]
        issued_token = create_access_token(str(user.id), token_version=user.token_version)
        _set_session_cookie(response, issued_token, request)
    elif token_str:
        resolved = await _resolve_user_from_token(token_str)
        if isinstance(resolved, TokenError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AuthErrorResponse(
                    code=token_error_to_code(resolved),
                    message="Token expired or invalid; call again with username+password",
                ).model_dump(),
            )
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AuthErrorResponse(
                    code=AuthErrorCode.TOKEN_INVALID,
                    message="Token expired or invalid; call again with username+password",
                ).model_dump(),
            )
        user = resolved
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthErrorResponse(
                code=AuthErrorCode.NOT_AUTHENTICATED,
                message="Provide a valid access_token cookie or username+password",
            ).model_dump(),
        )

    thread_body = ThreadCreateRequest(
        thread_id=body.thread_id,
        assistant_id=body.assistant_id,
        metadata=_strip_reserved_metadata(body.metadata),
    )
    user_token = set_current_user(user)
    try:
        return await create_thread_for_user(request, thread_body, owner_user_id=str(user.id))
    finally:
        reset_current_user(user_token)
