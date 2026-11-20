"""
backend/app/services/event_service.py
-------------------------------------
Business logic for Event management and venue capacity administration.

Key Features:
  - Event creation with automatic, safe seat initialization.
  - Event retrieval with pagination.
  - Optimistic concurrency control (OCC) using the `version` column.
    Concurrent edits with mismatched version numbers are rejected with HTTP 409 Conflict.
  - Seating capacity guardrails: capacity cannot be reduced below active/booked counts.
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingSeat, BookingStatus
from app.models.event import Event
from app.models.hold import Hold, HoldSeat
from app.models.seat import Seat, SeatStatus
from app.models.user import User, UserRole
from app.schemas.event import EventCreate, EventUpdate
from app.services.audit_service import log_audit


def generate_seat_numbers(total_seats: int, seats_per_row: int = 10) -> list[str]:
    """
    Generate human-readable, deterministic seat identifiers.
    E.g. A1..A10, B1..B10, ..., Z1..Z10, AA1..AA10, etc.
    """
    labels = []
    for i in range(total_seats):
        row_idx = i // seats_per_row
        col_idx = (i % seats_per_row) + 1

        # Calculate row label: A..Z, AA..ZZ
        if row_idx < 26:
            row_label = chr(65 + row_idx)
        else:
            first_char = chr(65 + (row_idx // 26) - 1)
            second_char = chr(65 + (row_idx % 26))
            row_label = f"{first_char}{second_char}"

        labels.append(f"{row_label}{col_idx}")
    return labels


def list_events(db: Session, skip: int = 0, limit: int = 100) -> list[Event]:
    """Retrieve all events ordered by start time."""
    return (
        db.query(Event)
        .order_by(Event.start_time.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_event_by_id(db: Session, event_id: uuid.UUID) -> Event:
    """Retrieve a single event by ID or raise HTTP 404."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with id '{event_id}' not found",
        )
    return event


def list_organizer_events(
    db: Session,
    organizer_id: uuid.UUID,
    is_admin: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> list[Event]:
    """Retrieve events belonging to the organizer, or all events if admin."""
    query = db.query(Event)
    if not is_admin:
        query = query.filter(Event.organizer_id == organizer_id)
    return query.order_by(Event.start_time.asc()).offset(skip).limit(limit).all()


def create_event(
    db: Session,
    event_data: EventCreate,
    creator: User | None = None,
) -> Event:
    """
    Create a new event and initialize its venue seats atomically.
    Assigns ownership to the creator if provided.
    """
    creator_id = creator.id if creator else None
    # 1. Create Event instance
    event = Event(
        title=event_data.title,
        description=event_data.description,
        location=event_data.location,
        start_time=event_data.start_time,
        booking_close_time=event_data.booking_close_time,
        total_seats=event_data.total_seats,
        version=1,
        organizer_id=creator_id,
    )
    db.add(event)
    db.flush()  # Generates event.id

    # 2. Generate and initialize all seats for this event
    seat_labels = generate_seat_numbers(event_data.total_seats)
    seats = [
        Seat(
            event_id=event.id,
            seat_number=label,
            status=SeatStatus.AVAILABLE,
        )
        for label in seat_labels
    ]
    db.add_all(seats)

    # 3. Audit log
    if creator:
        log_audit(
            db=db,
            action="EVENT_CREATED",
            actor_id=creator.id,
            actor_role=creator.role.value,
            event_id=event.id,
            details={"title": event.title, "total_seats": event.total_seats},
            commit=False,
        )

    db.commit()
    db.refresh(event)
    return event


def update_event(
    db: Session,
    event_id: uuid.UUID,
    event_data: EventUpdate,
    actor: User | None = None,
) -> Event:
    """
    Update an event using Optimistic Concurrency Control (OCC).

    Validates:
      - The caller is an Admin OR the Organizer who owns the event.
      - The provided `version` matches the database record.
      - If mismatched, raises HTTP 409 Conflict.
      - Capacity cannot be lowered below already-reserved or held seats.
      - Seat records are synchronized with total_seats change.
    """
    # 1. Check existing event
    event = get_event_by_id(db, event_id)

    # 2. Authorization check: Admin OR Owner Organizer
    if actor and actor.role != UserRole.ADMIN and event.organizer_id and event.organizer_id != actor.id:
        log_audit(
            db=db,
            action="ACCESS_DENIED",
            actor_id=actor.id,
            actor_role=actor.role.value,
            event_id=event.id,
            details={"reason": "organizer_not_owner", "attempted_action": "update_event"},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: You can only edit events you own.",
        )

    # 3. Check seating constraints if capacity changes
    if event_data.total_seats != event.total_seats:
        reserved_count = (
            db.query(func.count(Seat.id))
            .filter(
                Seat.event_id == event_id,
                Seat.status.in_([SeatStatus.BOOKED, SeatStatus.HELD]),
            )
            .scalar()
            or 0
        )
        if event_data.total_seats < reserved_count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot reduce total seats to {event_data.total_seats}. "
                    f"There are currently {reserved_count} booked or held seats."
                ),
            )

    # 3. Optimistic Locking atomic update:
    # Matches both event_id AND version. If version was updated by another
    # transaction, rowcount will be 0.
    stmt = (
        update(Event)
        .where(Event.id == event_id, Event.version == event_data.version)
        .values(
            title=event_data.title,
            description=event_data.description,
            location=event_data.location,
            start_time=event_data.start_time,
            booking_close_time=event_data.booking_close_time,
            total_seats=event_data.total_seats,
            version=Event.version + 1,
        )
    )
    result = db.execute(stmt)

    if result.rowcount == 0:
        # Version conflict! Refresh current state to inform user
        db.refresh(event)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Optimistic lock conflict: Event has been modified concurrently. "
                f"Your version: {event_data.version}, Current database version: {event.version}. "
                "Please reload the event details and re-apply changes."
            ),
        )

    # 4. Synchronize seats table if total_seats was expanded or shrunk
    current_seats = (
        db.query(Seat)
        .filter(Seat.event_id == event_id)
        .order_by(Seat.seat_number.asc())
        .all()
    )
    current_count = len(current_seats)

    if event_data.total_seats > current_count:
        # Generate new seats to add
        new_labels = generate_seat_numbers(event_data.total_seats)
        existing_labels = {s.seat_number for s in current_seats}
        seats_to_add = [
            Seat(event_id=event_id, seat_number=lbl, status=SeatStatus.AVAILABLE)
            for lbl in new_labels
            if lbl not in existing_labels
        ]
        db.add_all(seats_to_add)

    elif event_data.total_seats < current_count:
        # Safely remove unreserved seats from the end
        excess_count = current_count - event_data.total_seats
        available_seats = (
            db.query(Seat)
            .filter(Seat.event_id == event_id, Seat.status == SeatStatus.AVAILABLE)
            .order_by(Seat.id.desc())
            .limit(excess_count)
            .all()
        )
        for s in available_seats:
            db.delete(s)

    if actor:
        log_audit(
            db=db,
            action="EVENT_UPDATED",
            actor_id=actor.id,
            actor_role=actor.role.value,
            event_id=event_id,
            details={
                "new_version": event_data.version + 1,
                "title": event_data.title,
                "total_seats": event_data.total_seats,
            },
            commit=False,
        )

    db.commit()
    db.refresh(event)
    return event
