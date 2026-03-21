import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class RunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        # default runs server-side in Python, not via DB gen, so the ORM
        # always has the value immediately after flush without a round-trip.
        default=uuid.uuid4,
    )
    target_url: Mapped[str] = mapped_column(String, nullable=False)
    # VARCHAR(10) is enough for any HTTP verb (DELETE is 6 chars).
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    num_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        # name= keeps the Postgres type name stable if the class is renamed.
        Enum(RunStatus, name="run_status"),
        nullable=False,
        default=RunStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        # TIMESTAMPTZ stores the offset so reads are unambiguous regardless
        # of the Postgres server's local timezone setting.
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # back_populates keeps both sides of the relationship in sync in-memory.
    metrics: Mapped[list["Metrics"]] = relationship(
        "Metrics",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",  # avoids N+1 when loading a list of runs
    )


class Metrics(Base):
    __tablename__ = "metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        # ondelete="CASCADE" is the DB-level guard; the ORM cascade above
        # handles Python-side deletes — both are needed for safety.
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Native Postgres ARRAY avoids a separate latency_samples join table and
    # lets us pass the raw array directly to numpy for percentile computation.
    latencies: Mapped[list[float]] = mapped_column(
        ARRAY(Float), nullable=False, default=list
    )

    # Pre-computed percentiles stored alongside raw latencies so dashboards
    # can read aggregates cheaply without pulling the full array.
    p50: Mapped[float] = mapped_column(Float, nullable=False)
    p95: Mapped[float] = mapped_column(Float, nullable=False)
    p99: Mapped[float] = mapped_column(Float, nullable=False)

    # requests / total_wall_time_seconds
    throughput: Mapped[float] = mapped_column(Float, nullable=False)
    # error_count / num_requests — stored as 0.0–1.0 fraction
    error_rate: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped["Run"] = relationship("Run", back_populates="metrics")
