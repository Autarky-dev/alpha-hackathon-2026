"""
backend/app/models/event.py
---------------------------
Event model — represents a ticketed event (concert, conference, etc.).

Design notes
------------
- booking_close_time lets organisers set a hard cut-off for reservations
  independently of when the event starts.
- total_seats is a denormalised count kept on the Event so we can answer
  "how many seats does this event have?" in O(1) without counting rows.
- version is an integer used for optimistic locking: when two requests try
  to modify the same event concurrently, only the one that read the current
  version wins; the other gets a stale-data error and must retry.
  This prevents silent double-booking in the booking service (Phase 3).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Event(Base):
    """
    Maps to the 'events' table.

    Columns
    -------
    id                 : UUID primary key.
    title              : Short display name; required.
    description        : Optional long description.
    location           : Venue name or address; required.
    start_time         : When the event begins (timezone-aware).
    booking_close_time : Deadline after which no new bookings are accepted.
    total_seats        : Total number of seats in the venue.
    version            : Monotonically increasing integer for optimistic locking.
    created_at         : When this record was inserted (set by the database).

    Relationships
    -------------
    seats    : one Event → many Seats
    holds    : one Event → many Holds
    bookings : one Event → many Bookings
    """

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    location: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    # TIMESTAMP WITH TIME ZONE — always store in UTC, display in local time.
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    booking_close_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # BigInteger supports venues with >2 billion seats (future-proof).
    total_seats: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    # Starts at 1; incremented every time the event record is updated.
    # The booking service will use: UPDATE events SET version = version + 1
    # WHERE id = ? AND version = <expected> to detect concurrent modifications.
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    organizer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # func.now() tells SQLAlchemy to use the database's NOW() function as
    # the default, so the timestamp is always set by PostgreSQL, not the app.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # --- Relationships ---
    seats: Mapped[list["Seat"]] = relationship(  # type: ignore[name-defined]
        "Seat", back_populates="event", cascade="all, delete-orphan"
    )
    holds: Mapped[list["Hold"]] = relationship(  # type: ignore[name-defined]
        "Hold", back_populates="event", cascade="all, delete-orphan"
    )
    bookings: Mapped[list["Booking"]] = relationship(  # type: ignore[name-defined]
        "Booking", back_populates="event", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Event id={self.id} title={self.title!r}>"
