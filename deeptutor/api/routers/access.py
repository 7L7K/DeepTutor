"""Private tester access-code API."""

from __future__ import annotations

import os

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from deeptutor.services.access import (
    ACCESS_COOKIE_MAX_AGE_SECONDS,
    ACCESS_COOKIE_NAME,
    InvalidAccessCode,
    InvalidAccessToken,
    get_access_manager,
    sign_access_token,
)

router = APIRouter()


class AccessClaimRequest(BaseModel):
    access_code: str = Field(..., min_length=1, max_length=200)


def _public_tester(tester: dict) -> dict:
    return {
        "id": tester["id"],
        "tester_id": tester["id"],
        "display_name": tester["display_name"],
    }


async def get_current_tester(
    response: Response,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
) -> dict:
    manager = get_access_manager()
    try:
        return await manager.get_tester_from_token(access_token or "")
    except InvalidAccessToken as exc:
        _clear_access_cookie(response)
        raise HTTPException(status_code=401, detail="Not signed in") from exc


def _cookie_secure(request: Request) -> bool:
    override = os.getenv("DEEPTUTOR_ACCESS_COOKIE_SECURE", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    return request.url.scheme == "https" or forwarded_proto == "https"


def _set_access_cookie(request: Request, response: Response, tester_id: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        sign_access_token(tester_id),
        max_age=ACCESS_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )


def _clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        ACCESS_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )


@router.post("/claim")
async def claim_access(request: Request, response: Response, payload: AccessClaimRequest):
    manager = get_access_manager()
    try:
        tester = await manager.claim_code(payload.access_code)
    except InvalidAccessCode as exc:
        _clear_access_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid access code") from exc
    _set_access_cookie(request, response, tester["id"])
    return {"tester": _public_tester(tester)}


@router.get("/me")
async def get_me(
    tester: dict = Depends(get_current_tester),
):
    return {"tester": _public_tester(tester)}


@router.post("/logout")
async def logout(response: Response):
    _clear_access_cookie(response)
    return {"ok": True}
