"""
backend/app/services/checkin_service.py
---------------------------------------
Check-in operations, QR ticket cryptography, and attendee manifest service.

Key Features:
  - Cryptographically signed QR ticket tokens (HS256) containing zero sensitive data.
  - Row-level locking on Booking during check-in.
  - Duplicate check-in prevention (HTTP 409).
  - Validation: rejects unconfirmed or cancelled bookings (HTTP 400).
  - Event ownership authorization: organizers can only check in attendees for events they own.
  - Structured audit trail: logs CHECKIN events to the appropriate event shard.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import jwt
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.booking import Booking, BookingSeat, BookingStatus
from app.models.event import Event
from app.models.user import User, UserRole
from app.schemas.checkin import AttendeeItem, CheckInResponse, EventAttendeesResponse
from app.services.audit_service import log_audit


def generate_ticket_qr_token(booking_id: uuid.UUID, event_id: uuid.UUID) -> str:
    """
    Generate a tamper-proof, signed QR ticket token.
    Contains strictly non-sensitive identity claims (booking_id and event_id).
    """
    payload = {
        "type": "seatlock_ticket",
        "bid": str(booking_id),
        "eid": str(event_id),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_ticket_qr_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """
    Validate and decode a signed QR ticket token.
    Returns (booking_id, event_id) or raises HTTP 400.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "seatlock_ticket":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ticket token type")
        booking_id = uuid.UUID(payload["bid"])
        event_id = uuid.UUID(payload["eid"])
        return booking_id, event_id
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, corrupted, or forged QR ticket code.",
        )


def check_in_booking(
    db: Session,
    booking_id: uuid.UUID,
    actor: User,
    event_id: uuid.UUID | None = None,
    seat_numbers: list[str] | None = None,
) -> CheckInResponse:
    """
    Execute gate check-in for a booking.

    Validates:
      - Booking exists.
      - Actor is authorized: Admin or the Organizer who owns the event.
      - Booking matches event_id (if supplied).
      - Booking is CONFIRMED (rejects CANCELLED).
      - Rejects duplicate check-ins (HTTP 409).
      - Atomically updates checked_in_at and logs CHECKIN to event's audit shard.
    """
    try:
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
    except Exception:
        pass

    # 1. Lock booking record
    booking = db.query(Booking).filter(Booking.id == booking_id).with_for_update().first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking with id '{booking_id}' not found.",
        )

    # 2. Check event match
    if event_id and booking.event_id != event_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ticket event does not match the active venue check-in gate.",
        )

    # 3. Authorization check: Admin OR event's Organizer
    event = db.query(Event).filter(Event.id == booking.event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")

    if actor.role != UserRole.ADMIN and event.organizer_id != actor.id:
        # Audit access denied
        log_audit(
            db=db,
            action="ACCESS_DENIED",
            actor_id=actor.id,
            actor_role=actor.role.value,
            event_id=event.id,
            details={"reason": "organizer_not_owner", "attempted_booking_id": str(booking_id)},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: You can only check in attendees for events you own.",
        )

    # 4. Check booking status
    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot check in: Booking is {booking.status.value}.",
        )

    # 5. Prevent duplicate check-in
    if booking.checked_in_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Duplicate check-in: Booking was already checked in at {booking.checked_in_at.isoformat()}.",
        )

    # 6. Execute check-in
    now_utc = datetime.now(timezone.utc)
    booking.checked_in_at = now_utc

    # Update individual booking seats
    checked_in_seat_numbers = []
    for bs in booking.booking_seats:
        if seat_numbers is None or bs.seat.seat_number in seat_numbers:
            bs.checked_in_at = now_utc
            checked_in_seat_numbers.append(bs.seat.seat_number)

    # 7. Record CHECKIN audit event in the event's partition shard
    log_audit(
        db=db,
        action="CHECKIN",
        actor_id=actor.id,
        actor_role=actor.role.value,
        event_id=booking.event_id,
        details={
            "booking_id": str(booking.id),
            "attendee_id": str(booking.user_id),
            "seat_numbers": checked_in_seat_numbers,
            "checked_in_at": now_utc.isoformat(),
        },
        commit=False,
    )

    db.commit()
    db.refresh(booking)

    return CheckInResponse(
        booking_id=booking.id,
        event_id=booking.event_id,
        attendee_username=booking.user.username if booking.user else "Attendee",
        seat_numbers=checked_in_seat_numbers,
        checked_in_at=now_utc,
        message="Attendee successfully checked in.",
    )


def get_event_attendees(
    db: Session,
    event_id: uuid.UUID,
    actor: User,
) -> EventAttendeesResponse:
    """
    Retrieve the attendee manifest and check-in metrics for an event.
    Enforces that the caller is an Admin or the event's Organizer.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with id '{event_id}' not found.",
        )

    # Authorization
    if actor.role != UserRole.ADMIN and event.organizer_id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: You can only view attendee manifests for events you own.",
        )

    bookings = (
        db.query(Booking)
        .filter(Booking.event_id == event_id)
        .order_by(Booking.created_at.desc())
        .all()
    )

    attendees = []
    total_seats_reserved = 0
    total_checked_in = 0

    for b in bookings:
        seat_numbers = [bs.seat.seat_number for bs in b.booking_seats]
        if b.status == BookingStatus.CONFIRMED:
            total_seats_reserved += len(seat_numbers)
            if b.checked_in_at:
                total_checked_in += len(seat_numbers)

        attendees.append(
            AttendeeItem(
                booking_id=b.id,
                user_id=b.user_id,
                username=b.user.username if b.user else "Unknown",
                seat_numbers=seat_numbers,
                status=b.status.value,
                checked_in_at=b.checked_in_at,
                created_at=b.created_at,
            )
        )

    pending_check_in = max(0, total_seats_reserved - total_checked_in)

    return EventAttendeesResponse(
        event_id=event.id,
        event_title=event.title,
        total_bookings=len(bookings),
        total_seats_reserved=total_seats_reserved,
        total_checked_in=total_checked_in,
        pending_check_in=pending_check_in,
        attendees=attendees,
    )
