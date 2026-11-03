import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.security import decode_token
from app.models.access_code import AccessCode

# auto_error=False so we return a uniform 401 ourselves.
_bearer = HTTPBearer(auto_error=False)

# last_used_at is a usage signal, not an audit log: skip the write if it was
# updated recently so a busy page does not turn every request into a DB write.
_LAST_USED_RESOLUTION = timedelta(seconds=60)


@dataclass(frozen=True)
class Principal:
    # None = the shared demo owner (only reachable by admin / auth disabled).
    code_id: uuid.UUID | None
    label: str | None
    is_admin: bool


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """
    Resolve the caller from a Bearer token.

    The code is re-checked in the database on every request (not only at
    login) so revoking a code takes effect immediately instead of when its
    token expires.
    """
    if not settings.auth_enabled:
        # Local development: behave as an admin that owns the demo scope.
        return Principal(code_id=None, label=None, is_admin=True)

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    sub = decode_token(credentials.credentials)
    if sub is None:
        raise _unauthorized()
    try:
        code_id = uuid.UUID(sub)
    except ValueError:
        raise _unauthorized()

    code = await db.get(AccessCode, code_id)
    if code is None or code.revoked_at is not None:
        raise _unauthorized()

    now = datetime.now(timezone.utc)
    last = code.last_used_at
    if last is not None and last.tzinfo is None:
        # SQLite (tests) drops tzinfo; Postgres returns aware values.
        last = last.replace(tzinfo=timezone.utc)
    if last is None or now - last > _LAST_USED_RESOLUTION:
        code.last_used_at = now
        await db.commit()

    return Principal(code_id=code.id, label=code.label, is_admin=False)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def require_admin(
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    """
    Guard for admin routes. Fails closed: if ADMIN_API_KEY is unset the routes
    are unusable (403), never open. When auth is disabled (local dev) there is
    no gate, matching the rest of the local experience.
    """
    if not settings.auth_enabled:
        return
    if not settings.admin_api_key or x_admin_key is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if not hmac.compare_digest(
        x_admin_key.encode("utf-8"), settings.admin_api_key.encode("utf-8")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


AdminOnly = Depends(require_admin)


async def require_llm_benchmark_enabled() -> None:
    """
    Feature flag for POST /benchmark/llm. The route forwards a caller-supplied API
    key to a caller-supplied endpoint, so it is off by default on a hosted
    (auth-enabled) deployment. 404, not 403: when off it should look like it
    does not exist, with the same body as an unknown route.
    """
    if not settings.llm_benchmark_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
