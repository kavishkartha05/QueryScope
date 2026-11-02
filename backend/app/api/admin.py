import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminOnly
from app.api.runs import _replace_baseline, _run_to_response
from app.core.db import get_db
from app.core.security import generate_code, hash_code, is_valid_label
from app.models.access_code import AccessCode
from app.models.run import Run
from app.schemas.run import RunResponse

# Every route here requires X-Admin-Key; there is no Bearer-token path in.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[AdminOnly])

DB = Annotated[AsyncSession, Depends(get_db)]


class CodeSummary(BaseModel):
    id: uuid.UUID
    label: str
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    run_count: int


class CreateCodeRequest(BaseModel):
    label: str = Field(min_length=3, max_length=42)


class CreatedCode(BaseModel):
    id: uuid.UUID
    label: str
    # The plaintext code is returned exactly once, here. Only its keyed hash
    # is stored, so it cannot be shown again.
    code: str


@router.get("/codes", response_model=list[CodeSummary])
async def list_codes(db: DB) -> list[CodeSummary]:
    run_counts = (
        select(Run.access_code_id, func.count(Run.id).label("run_count"))
        .where(Run.access_code_id.is_not(None))
        .group_by(Run.access_code_id)
        .subquery()
    )
    result = await db.execute(
        select(AccessCode, func.coalesce(run_counts.c.run_count, 0))
        .outerjoin(run_counts, run_counts.c.access_code_id == AccessCode.id)
        .order_by(AccessCode.created_at.desc())
    )
    summaries = []
    for code, run_count in result.all():
        summaries.append(
            CodeSummary(
                id=code.id,
                label=code.label,
                created_at=code.created_at,
                revoked_at=code.revoked_at,
                last_used_at=code.last_used_at,
                run_count=int(run_count),
            )
        )
    return summaries


@router.post("/codes", response_model=CreatedCode, status_code=201)
async def create_code(req: CreateCodeRequest, db: DB) -> CreatedCode:
    if not is_valid_label(req.label):
        raise HTTPException(
            status_code=422,
            detail="label must be 3-42 chars of lowercase a-z, 0-9 and hyphen",
        )
    code_value = generate_code(req.label)
    row = AccessCode(label=req.label, code_hash=hash_code(code_value))
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A code with that label already exists")
    await db.refresh(row)
    return CreatedCode(id=row.id, label=row.label, code=code_value)


@router.post("/codes/{code_id}/revoke", response_model=CodeSummary)
async def revoke_code(code_id: uuid.UUID, db: DB) -> CodeSummary:
    row = await db.get(AccessCode, code_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Code not found")
    # Idempotent: keep the original revocation time on repeat calls.
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)
    count = await db.execute(
        select(func.count(Run.id)).where(Run.access_code_id == row.id)
    )
    return CodeSummary(
        id=row.id,
        label=row.label,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        run_count=int(count.scalar_one()),
    )


@router.patch("/runs/{run_id}/baseline", response_model=RunResponse)
async def set_demo_baseline(run_id: uuid.UUID, db: DB) -> RunResponse:
    """Pin the shared demo baseline. Recruiters' own baselines are untouched."""
    run = await db.get(Run, run_id)
    if run is None or run.access_code_id is not None:
        raise HTTPException(status_code=404, detail="Demo run not found")
    if run.is_baseline:
        raise HTTPException(status_code=400, detail="Run is already the baseline")
    await _replace_baseline(db, run, Run.access_code_id.is_(None))
    return _run_to_response(run, baseline=run)
