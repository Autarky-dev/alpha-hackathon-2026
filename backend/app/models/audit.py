"""
backend/app/models/audit.py
----------------------------
Audit log models — immutable record of every significant action in SeatLock.

Design: manual hash-partitioning across 4 tables
-------------------------------------------------
A single audit_logs table in a busy reservation system can grow to tens of
millions of rows quickly. Rather than a single large table, we use 4
structurally identical tables (audit_logs_0 … audit_logs_3) and route writes
to the correct table using:

    table_index = int(event_id_uuid) % 4

This spreads I/O across 4 table segments. Each table has its own indexes,
so index sizes stay manageable. All 4 are defined here using a shared
mixin to avoid repeating the column definitions.

Why not PostgreSQL declarative partitioning?
  Declarative partitioning requires the partition key in the primary key,
  complicates SQLAlchemy model definitions, and needs PostgreSQL 10+.
  Manual partitioning is simpler to understand and debug for a hackathon,
  and can be migrated to declarative partitioning later without schema changes.

What is logged?
  - actor_id    : who performed the action (user UUID, nullable for system actions)
  - actor_role  : their role at the time of the action
  - event_id    : which event this action relates to (the routing key)
  - action      : short verb, e.g. "seat_held", "booking_confirmed", "hold_expired"
  - details     : JSONB blob for structured extra data (seat numbers, old/new status)
  - created_at  : exact UTC timestamp of the action
"""

import uuid
import enum
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.database import Base


# ---------------------------------------------------------------------------
# Shared column definitions via a mixin class
# ---------------------------------------------------------------------------
# A mixin is a plain Python class (not a SQLAlchemy model) that defines
# columns. Each AuditLog table inherits from BOTH Base and this mixin,
# getting all these columns without us having to copy-paste them four times.
# ---------------------------------------------------------------------------
class AuditLogMixin:
    """
    Column definitions shared across all four audit log tables.
    Not a table itself — just a reusable set of columns.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # Nullable: system-triggered actions (e.g. expiry sweep) have no actor.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # Stored as plain text so we don't need an FK to users (audit logs must
    # survive even if the user row is deleted).
    actor_role: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # The event this action relates to — used as the partition routing key.
    # Stored as text (not FK) for the same survivability reason as actor_id.
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # Short verb describing what happened. Examples:
    #   "seat_held", "hold_expired", "booking_confirmed", "booking_cancelled"
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Flexible JSONB field for structured extra context.
    # Example: {"seat_numbers": ["A1", "A2"], "hold_id": "uuid..."}
    details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    # Always set by the database to guarantee accurate UTC timestamps
    # regardless of application server timezone.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Four audit log tables — structurally identical, routed by event_id % 4
# ---------------------------------------------------------------------------

class AuditLog0(AuditLogMixin, Base):
    """Audit log partition 0 — receives events where int(event_id) % 4 == 0."""
    __tablename__ = "audit_logs_0"
    __table_args__ = (
        Index("ix_audit_logs_0_event_id",   "event_id"),
        Index("ix_audit_logs_0_actor_id",   "actor_id"),
        Index("ix_audit_logs_0_action",     "action"),
        Index("ix_audit_logs_0_created_at", "created_at"),
    )


class AuditLog1(AuditLogMixin, Base):
    """Audit log partition 1 — receives events where int(event_id) % 4 == 1."""
    __tablename__ = "audit_logs_1"
    __table_args__ = (
        Index("ix_audit_logs_1_event_id",   "event_id"),
        Index("ix_audit_logs_1_actor_id",   "actor_id"),
        Index("ix_audit_logs_1_action",     "action"),
        Index("ix_audit_logs_1_created_at", "created_at"),
    )


class AuditLog2(AuditLogMixin, Base):
    """Audit log partition 2 — receives events where int(event_id) % 4 == 2."""
    __tablename__ = "audit_logs_2"
    __table_args__ = (
        Index("ix_audit_logs_2_event_id",   "event_id"),
        Index("ix_audit_logs_2_actor_id",   "actor_id"),
        Index("ix_audit_logs_2_action",     "action"),
        Index("ix_audit_logs_2_created_at", "created_at"),
    )


class AuditLog3(AuditLogMixin, Base):
    """Audit log partition 3 — receives events where int(event_id) % 4 == 3."""
    __tablename__ = "audit_logs_3"
    __table_args__ = (
        Index("ix_audit_logs_3_event_id",   "event_id"),
        Index("ix_audit_logs_3_actor_id",   "actor_id"),
        Index("ix_audit_logs_3_action",     "action"),
        Index("ix_audit_logs_3_created_at", "created_at"),
    )
