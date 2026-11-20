"""
backend/app/schemas/booking.py
------------------------------
Pydantic schemas for seat maps, hold reservations, and bookings.

Includes:
  - SeatResponse / SeatMapResponse : Detailed venue layout & availability status.
  - HoldCreateRequest / HoldResponse : Temporary 5-minute seat lock request & confirmation.
  - BookingResponse : Permanent reservation record.
  - CancelBookingResponse : Cancellation confirmation.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.models.booking import BookingStatus
from app.models.seat import SeatStatus


class SeatResponse(BaseModel):
    """Status of an individual seat within an event."""
    id: uuid.UUID
    event_id: uuid.UUID
    seat_number: str
    status: SeatStatus
    is_held_by_me: bool = False

    model_config = ConfigDict(from_attributes=True)


class SeatMapResponse(BaseModel):
    """Complete seat map for an event."""
    event_id: uuid.UUID
    total_seats: int
    available_count: int
    held_count: int
    booked_count: int
    seats: list[SeatResponse]


class HoldCreateRequest(BaseModel):
    """
    Request to hold 1-4 seats for an event.
    Must provide seat numbers (e.g. ['A1', 'A2']).
    """
    seat_numbers: list[str] = Field(
        ...,
        min_length=1,
        max_length=4,
        description="List of 1 to 4 unique seat numbers to hold",
    )


class HoldResponse(BaseModel):
    """Details of an active seat hold."""
    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime
    seat_numbers: list[str]
    message: str = "Seats successfully held for 5 minutes"

    model_config = ConfigDict(from_attributes=True)


class BookingResponse(BaseModel):
    """Details of a confirmed or cancelled booking."""
    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    status: BookingStatus
    created_at: datetime
    seat_numbers: list[str]
    event_title: str | None = None
    checked_in_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CancelBookingResponse(BaseModel):
    """Response returned upon cancelling a booking."""
    id: uuid.UUID
    status: BookingStatus
    message: str = "Booking successfully cancelled and seats released"
