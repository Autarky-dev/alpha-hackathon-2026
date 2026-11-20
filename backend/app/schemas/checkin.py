"""
backend/app/schemas/checkin.py
------------------------------
Pydantic schemas for check-in operations, QR ticket validation, and attendee manifests.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CheckInRequest(BaseModel):
    """Payload to check in an attendee via booking_id or scanned QR ticket."""
    booking_id: uuid.UUID | None = None
    qr_token: str | None = None
    seat_numbers: list[str] | None = None


class CheckInResponse(BaseModel):
    """Confirmation returned when check-in succeeds."""
    booking_id: uuid.UUID
    event_id: uuid.UUID
    attendee_username: str
    seat_numbers: list[str]
    checked_in_at: datetime
    message: str = "Attendee successfully checked in"


class AttendeeItem(BaseModel):
    """Attendee record within an event's manifest."""
    booking_id: uuid.UUID
    user_id: uuid.UUID
    username: str
    seat_numbers: list[str]
    status: str
    checked_in_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EventAttendeesResponse(BaseModel):
    """Manifest of all attendees and check-in metrics for an event."""
    event_id: uuid.UUID
    event_title: str
    total_bookings: int
    total_seats_reserved: int
    total_checked_in: int
    pending_check_in: int
    attendees: list[AttendeeItem]


class TicketTokenResponse(BaseModel):
    """Secure signed QR ticket token."""
    booking_id: uuid.UUID
    ticket_token: str
