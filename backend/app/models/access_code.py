import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AccessCode(Base):
    """
    One row per recipient code. Only a keyed hash of the code is stored, so a
    database leak does not reveal usable codes. Rows are never deleted: a code
    is revoked by setting revoked_at, which keeps run attribution intact.
    """

    __tablename__ = "access_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Human-readable recipient tag, e.g. "stripe-rebecca". Not a secret.
    label: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Hex HMAC-SHA256 of the code. Unique + indexed so login is one lookup.
    code_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
