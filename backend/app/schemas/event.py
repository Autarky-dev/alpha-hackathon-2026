"""
backend/app/schemas/event.py
----------------------------
Pydantic schemas for event management requests and responses.

Includes:
  - EventCreate: Validates event creation input (dates, positive seat count, required fields).
  - EventUpdate: Validates updates with optimistic locking version field.
  - EventResponse: Output representation of an Event record.
"""

import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventCreate(BaseModel):
    """Schema for creating a new event (Organizers & Admins)."""
    title: str = Field(..., min_length=2, max_length=200, description="Event title")
    description: str | None = Field(None, max_length=5000, description="Optional event description")
    location: str = Field(..., min_length=2, max_length=300, description="Venue or location")
    start_time: datetime = Field(..., description="When the event starts (UTC)")
    booking_close_time: datetime = Field(..., description="When ticket reservations close (UTC)")
    total_seats: int = Field(..., gt=0, le=10000, description="Total seating capacity (1-10000)")

    @field_validator("booking_close_time")
    @classmethod
    def validate_booking_close_time(cls, v: datetime, info) -> datetime:
        start = info.data.get("start_time")
        if start and v > start:
            raise ValueError("booking_close_time cannot be after start_time")
        return v

    @field_validator("start_time")
    @classmethod
    def validate_start_time(cls, v: datetime) -> datetime:
        # In testing/dev, allow current or future timestamps
        return v


class EventUpdate(BaseModel):
    """
    Schema for updating an existing event.
    Requires version for optimistic concurrency control (OCC).
    """
    title: str = Field(..., min_length=2, max_length=200)
    description: str | None = Field(None, max_length=5000)
    location: str = Field(..., min_length=2, max_length=300)
    start_time: datetime
    booking_close_time: datetime
    total_seats: int = Field(..., gt=0, le=10000)
    version: int = Field(..., ge=1, description="Expected version for optimistic locking")

    @field_validator("booking_close_time")
    @classmethod
    def validate_booking_close_time(cls, v: datetime, info) -> datetime:
        start = info.data.get("start_time")
        if start and v > start:
            raise ValueError("booking_close_time cannot be after start_time")
        return v


class EventResponse(BaseModel):
    """Public representation of an Event."""
    id: uuid.UUID
    title: str
    description: str | None
    location: str
    start_time: datetime
    booking_close_time: datetime
    total_seats: int
    version: int
    created_at: datetime
    organizer_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)
