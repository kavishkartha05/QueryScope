"""
Create, list and revoke access codes directly against the database.

Run from the backend/ directory (so pydantic-settings finds .env and the app
package imports resolve):

    python scripts/manage_codes.py create stripe-rebecca
    python scripts/manage_codes.py list
    python scripts/manage_codes.py revoke stripe-rebecca

CODE_PEPPER must match the value the server uses, or codes created here will
not validate there. `create` prints the new code ONCE; only its keyed hash is
stored, so it cannot be recovered later. Treat the output as a secret.
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import AsyncSessionLocal  # noqa: E402
from app.core.security import generate_code, hash_code, is_valid_label  # noqa: E402
from app.models.access_code import AccessCode  # noqa: E402
from app.models.run import Run  # noqa: E402


async def cmd_create(label: str) -> int:
    if len(settings.code_pepper) < 32:
        print("CODE_PEPPER must be set to at least 32 characters.", file=sys.stderr)
        return 1
    if not is_valid_label(label):
        print("label must be 3-42 chars of lowercase a-z, 0-9 and hyphen.", file=sys.stderr)
        return 1
    code_value = generate_code(label)
    async with AsyncSessionLocal() as session:
        session.add(AccessCode(label=label, code_hash=hash_code(code_value)))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            print(f"A code labelled '{label}' already exists.", file=sys.stderr)
            return 1
    print(f"label: {label}")
    print(f"code:  {code_value}")
    print("Shown once. Store it somewhere safe before closing this terminal.")
    return 0


async def cmd_list() -> int:
    async with AsyncSessionLocal() as session:
        counts = (
            select(Run.access_code_id, func.count(Run.id).label("n"))
            .where(Run.access_code_id.is_not(None))
            .group_by(Run.access_code_id)
            .subquery()
        )
        result = await session.execute(
            select(AccessCode, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.access_code_id == AccessCode.id)
            .order_by(AccessCode.created_at)
        )
        print(f"{'label':<44} {'status':<8} {'runs':>5}  last used")
        for code, n in result.all():
            status = "revoked" if code.revoked_at else "active"
            last = code.last_used_at.isoformat(timespec="seconds") if code.last_used_at else "never"
            print(f"{code.label:<44} {status:<8} {int(n):>5}  {last}")
    return 0


async def cmd_revoke(label: str) -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(AccessCode).where(AccessCode.label == label))
        row = result.scalars().first()
        if row is None:
            print(f"No code labelled '{label}'.", file=sys.stderr)
            return 1
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await session.commit()
        print(f"Revoked '{label}'. Its sessions stop working on the next request.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage QueryScope access codes")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create a new code")
    create.add_argument("label")
    sub.add_parser("list", help="list codes with run counts")
    revoke = sub.add_parser("revoke", help="revoke a code by label")
    revoke.add_argument("label")
    args = parser.parse_args()

    if args.command == "create":
        return asyncio.run(cmd_create(args.label))
    if args.command == "list":
        return asyncio.run(cmd_list())
    return asyncio.run(cmd_revoke(args.label))


if __name__ == "__main__":
    sys.exit(main())
