"""Safe validation handling for the browser login endpoint."""

from __future__ import annotations

import json

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from deeptutor.services import auth as auth_service
from deeptutor.services.auth_diagnostics import (
    auth_attempt_headers,
    emit_auth_attempt,
    resolve_attempt_id,
    validated_request_id,
)


async def login_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    """Keep malformed login responses generic while recording safe diagnostics."""
    if request.url.path == "/api/v1/auth/login":
        username: str | None = None
        try:
            payload = json.loads((await request.body()).decode("utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("username"), str):
                username = payload["username"]
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            pass

        attempt_id = resolve_attempt_id()
        request_id = validated_request_id(
            request.headers.get("x-request-id"),
            auth_secret=auth_service.AUTH_SECRET,
        )
        emit_auth_attempt(
            attempt_id=attempt_id,
            request_id=request_id,
            username=username,
            user_agent=request.headers.get("user-agent"),
            auth_secret=auth_service.AUTH_SECRET,
            lookup="none",
            account_state="unknown",
            password_result="not_checked",
            auth_mode="pocketbase" if auth_service.POCKETBASE_ENABLED else "standard",
            outcome="validation_failure",
        )
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid login request"},
            headers=auth_attempt_headers(attempt_id),
        )

    return await request_validation_exception_handler(request, exc)
