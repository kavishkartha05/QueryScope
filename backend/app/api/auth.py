from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    client_ip,
    create_token,
    hash_code,
    hashes_match,
    login_limiter,
)
from app.models.access_code import AccessCode

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: datetime
    label: str


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoginResponse:
    if not settings.auth_enabled:
        raise HTTPException(status_code=404, detail="Authentication is disabled")

    ip = client_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
    )

    wait = login_limiter.retry_after(ip)
    if wait > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )

    # Same work on every path (hash, one indexed lookup, constant-time compare)
    # and one generic error, so responses do not reveal whether a code is
    # unknown, malformed or revoked.
    submitted_hash = hash_code(req.code)
    result = await db.execute(select(AccessCode).where(AccessCode.code_hash == submitted_hash))
    code = result.scalars().first()

    valid = (
        code is not None
        and hashes_match(code.code_hash, submitted_hash)
        and code.revoked_at is None
    )
    if not valid or code is None:
        login_limiter.record_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code"
        )

    code.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    login_limiter.reset_ip(ip)

    token, expires_at = create_token(str(code.id))
    return LoginResponse(token=token, expires_at=expires_at, label=code.label)
