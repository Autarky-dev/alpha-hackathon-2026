"""
backend/app/models/hold.py
--------------------------
Hold and HoldSeat models — the temporary seat reservation layer.

Design notes
------------
A Hold represents a user's intent to book a group of seats. It is a
time-limited lock:

  1. User requests seats → Hold row is created with an expires_at timestamp.
  2. Each seat in the request gets a HoldSeat row; Seat.status → HELD.
  3. If the user completes payment / confirms: Hold → Booking.
  4. If expires_at passes without confirmation, a background job releases the
     hold: HoldSeat rows deleted, Seat.status → AVAILABLE, Hold deleted.

Why a separate HoldSeat join table instead of storing seat_ids in the Hold?
  Relational normalisation. Each seat is a first-class row with its own
  status. The join table lets us query "which holds include seat X?" in O(log n)
  with a simple index, and foreign keys enforce referential integrity.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Hold(Base):
    """
    Maps to the 'holds' table.

    Columns
    -------
    id         : UUID primary key.
    user_id    : FK → users.id. Who created this hold.
    event_id   : FK → events.id. Which event the held seats belong to.
    expires_at : When this hold expires and seats become available again.
    created_at : When the hold was created (set by the database).

    Relationships
    -------------
    user       : many Holds → one User
    event      : many Holds → one Event
    hold_seats : one Hold → many HoldSeat rows (the actual seats being held)
    """

    __tablename__ = "holds"

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

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # --- Relationships ---
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="holds"
    )
    event: Mapped["Event"] = relationship(  # type: ignore[name-defined]
        "Event", back_populates="holds"
    )
    hold_seats: Mapped[list["HoldSeat"]] = relationship(
        "HoldSeat", back_populates="hold", cascade="all, delete-orphan"
    )

    # --- Indexes ---
    __table_args__ = (
        # Expiry sweeper query: "find all holds that have expired" runs frequently.
        Index("ix_holds_expires_at", "expires_at"),
        # Look up all active holds for a specific user+event combination.
        Index("ix_holds_user_event", "user_id", "event_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Hold id={self.id} user_id={self.user_id} "
            f"event_id={self.event_id} expires_at={self.expires_at}>"
        )


class HoldSeat(Base):
    """
    Maps to the 'hold_seats' table.

    Join table linking a Hold to the specific Seats it covers.
    Uses a composite primary key (hold_id, seat_id) so the same seat
    cannot appear twice within the same hold.

    Columns
    -------
    hold_id : FK → holds.id (part of composite PK).
    seat_id : FK → seats.id (part of composite PK).

    Relationships
    -------------
    hold : many HoldSeat → one Hold
    seat : many HoldSeat → one Seat
    """

    __tablename__ = "hold_seats"

    hold_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("holds.id", ondelete="CASCADE"),
        primary_key=True,   # composite PK part 1
    )

    seat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seats.id", ondelete="CASCADE"),
        primary_key=True,   # composite PK part 2
    )

    # --- Relationships ---
    hold: Mapped["Hold"] = relationship("Hold", back_populates="hold_seats")
    seat: Mapped["Seat"] = relationship(  # type: ignore[name-defined]
        "Seat", back_populates="hold_seats"
    )

    def __repr__(self) -> str:
        return f"<HoldSeat hold_id={self.hold_id} seat_id={self.seat_id}>"
