"""
backend/app/models/booking.py
------------------------------
Booking and BookingSeat models — the confirmed reservation layer.

Design notes
------------
A Booking is created when a Hold is converted into a confirmed reservation.
Like Hold/HoldSeat, the actual seats are stored in a join table (BookingSeat)
rather than as an array column, preserving referential integrity and
enabling per-seat queries.

BookingStatus lifecycle:
  CONFIRMED → the booking is active; seats are BOOKED.
  CANCELLED → the user or admin cancelled; seats return to AVAILABLE.

We keep cancelled bookings in the table (soft delete) so the audit trail
remains intact and we can answer "who had this seat previously?".
"""

import uuid
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as PgEnum, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BookingStatus(str, enum.Enum):
    """
    States a Booking can be in.

    CONFIRMED : Active reservation; associated seats are BOOKED.
    CANCELLED : Reservation was cancelled; associated seats are AVAILABLE.
    """
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Booking(Base):
    """
    Maps to the 'bookings' table.

    Columns
    -------
    id         : UUID primary key.
    user_id    : FK → users.id. Who made this booking.
    event_id   : FK → events.id. Which event was booked.
    status     : BookingStatus enum.
    created_at : When the booking was confirmed (set by the database).

    Relationships
    -------------
    user          : many Bookings → one User
    event         : many Bookings → one Event
    booking_seats : one Booking → many BookingSeat rows
    """

    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[BookingStatus] = mapped_column(
        PgEnum(BookingStatus, name="booking_status", create_type=True, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=BookingStatus.CONFIRMED,
        server_default="confirmed",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # --- Relationships ---
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="bookings"
    )
    event: Mapped["Event"] = relationship(  # type: ignore[name-defined]
        "Event", back_populates="bookings"
    )
    booking_seats: Mapped[list["BookingSeat"]] = relationship(
        "BookingSeat", back_populates="booking", cascade="all, delete-orphan"
    )

    # --- Indexes ---
    __table_args__ = (
        # Most common lookup: "all bookings for user X" and "all bookings for event Y".
        Index("ix_bookings_user_id", "user_id"),
        Index("ix_bookings_event_id", "event_id"),
        # Filtering by status is common (e.g. show only CONFIRMED bookings).
        Index("ix_bookings_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Booking id={self.id} user_id={self.user_id} "
            f"event_id={self.event_id} status={self.status}>"
        )


class BookingSeat(Base):
    """
    Maps to the 'booking_seats' table.

    Join table linking a Booking to the specific Seats it covers.
    Composite primary key prevents the same seat appearing twice in one booking.

    Columns
    -------
    booking_id : FK → bookings.id (part of composite PK).
    seat_id    : FK → seats.id   (part of composite PK).

    Relationships
    -------------
    booking : many BookingSeat → one Booking
    seat    : many BookingSeat → one Seat
    """

    __tablename__ = "booking_seats"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bookings.id", ondelete="CASCADE"),
        primary_key=True,   # composite PK part 1
    )

    seat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seats.id", ondelete="CASCADE"),
        primary_key=True,   # composite PK part 2
    )

    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # --- Relationships ---
    booking: Mapped["Booking"] = relationship("Booking", back_populates="booking_seats")
    seat: Mapped["Seat"] = relationship(  # type: ignore[name-defined]
        "Seat", back_populates="booking_seats"
    )

    def __repr__(self) -> str:
        return f"<BookingSeat booking_id={self.booking_id} seat_id={self.seat_id}>"
