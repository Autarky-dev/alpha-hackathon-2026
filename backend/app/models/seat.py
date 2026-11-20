"""
backend/app/models/seat.py
--------------------------
Seat model — represents one physical seat in an event's venue.

Design notes
------------
- Status is enforced at the PostgreSQL ENUM level, not just in Python.
  Valid states: available → held → booked.
  A seat cannot be in an invalid state; the database rejects the insert.

- The composite unique constraint on (event_id, seat_number) prevents
  two rows with the same seat label within the same event, even if two
  concurrent requests slip past the application-level checks.

- An index on (event_id, status) supports the most common query pattern:
  "give me all AVAILABLE seats for event X" — which the booking service
  will run on every reservation attempt.
"""

import uuid
import enum

from sqlalchemy import Enum as PgEnum, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SeatStatus(str, enum.Enum):
    """
    The lifecycle of a seat.

    AVAILABLE : nobody is touching this seat; can be held or booked.
    HELD      : a user has a temporary lock on this seat; it will expire.
    BOOKED    : confirmed reservation; seat is permanently taken.
    """
    AVAILABLE = "available"
    HELD      = "held"
    BOOKED    = "booked"


class Seat(Base):
    """
    Maps to the 'seats' table.

    Columns
    -------
    id          : UUID primary key.
    event_id    : FK → events.id. Which event this seat belongs to.
    seat_number : Human-readable label, e.g. "A12", "Row 3 Seat 7".
    status      : Current state of the seat (SeatStatus enum).

    Relationships
    -------------
    event      : many Seats → one Event
    hold_seats : one Seat → many HoldSeat join rows
    booking_seats : one Seat → many BookingSeat join rows
    """

    __tablename__ = "seats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )

    seat_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    status: Mapped[SeatStatus] = mapped_column(
        PgEnum(SeatStatus, name="seat_status", create_type=True, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=SeatStatus.AVAILABLE,
        server_default="available",
    )

    # --- Relationships ---
    event: Mapped["Event"] = relationship(  # type: ignore[name-defined]
        "Event", back_populates="seats"
    )
    hold_seats: Mapped[list["HoldSeat"]] = relationship(  # type: ignore[name-defined]
        "HoldSeat", back_populates="seat", cascade="all, delete-orphan"
    )
    booking_seats: Mapped[list["BookingSeat"]] = relationship(  # type: ignore[name-defined]
        "BookingSeat", back_populates="seat", cascade="all, delete-orphan"
    )

    # --- Constraints and indexes ---
    __table_args__ = (
        # No duplicate seat labels within the same event.
        UniqueConstraint("event_id", "seat_number", name="uq_seats_event_seat_number"),
        # Fast lookup of available seats for an event — used on every booking.
        Index("ix_seats_event_id_status", "event_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Seat id={self.id} event_id={self.event_id} "
            f"seat_number={self.seat_number!r} status={self.status}>"
        )
