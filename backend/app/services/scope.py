"""
Ownership scoping for runs.

Every run has an owner: an access_code_id, or NULL for the shared demo owner.
  - visible to a caller: their own runs plus demo runs
  - modifiable by a caller: only their own runs (demo runs: admin only)

All queries go through these helpers so isolation is defined in one place.
"""
import uuid

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import Run

# Value stored in the Azure Search access_code_id field for demo-owned runs.
# Azure filters cannot match a missing value with "eq", so demo gets a literal.
DEMO_OWNER_VALUE = "demo"


def visible_clause(code_id: uuid.UUID | None) -> ColumnElement[bool]:
    """Own runs OR demo runs. With no code (admin/local), only demo runs."""
    if code_id is None:
        return Run.access_code_id.is_(None)
    return or_(Run.access_code_id == code_id, Run.access_code_id.is_(None))


def owned_clause(code_id: uuid.UUID | None) -> ColumnElement[bool]:
    """Runs the caller may modify. With no code, the demo scope."""
    if code_id is None:
        return Run.access_code_id.is_(None)
    return Run.access_code_id == code_id


async def effective_baseline(db: AsyncSession, code_id: uuid.UUID | None) -> Run | None:
    """The caller's own baseline, falling back to the demo baseline."""
    if code_id is not None:
        own = await db.execute(
            select(Run).where(and_(Run.access_code_id == code_id, Run.is_baseline.is_(True)))
        )
        own_run = own.scalars().first()
        if own_run is not None:
            return own_run
    demo = await db.execute(
        select(Run).where(and_(Run.access_code_id.is_(None), Run.is_baseline.is_(True)))
    )
    return demo.scalars().first()


def index_owner_value(code_id: uuid.UUID | None) -> str:
    return DEMO_OWNER_VALUE if code_id is None else str(code_id)


def search_filter(code_id: uuid.UUID | None) -> str:
    """
    OData filter for Azure AI Search: own OR demo. Applied inside the vector
    query (not by post-filtering the top-k), so it cannot come back empty just
    because other owners' documents out-rank the caller's.

    "eq null" also matches documents indexed before this field existed; they
    predate access codes and are treated as demo data.
    """
    clauses = [f"access_code_id eq '{DEMO_OWNER_VALUE}'", "access_code_id eq null"]
    if code_id is not None:
        # str(UUID) is hex plus hyphens, so it cannot break out of the quotes.
        clauses.insert(0, f"access_code_id eq '{uuid.UUID(str(code_id))}'")
    return " or ".join(clauses)
