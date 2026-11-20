"""
backend/app/services/booking_service.py
---------------------------------------
Core seat reservation, locking, and booking engine for SeatLock.

Key Architectural Guarantees:
  1. Concurrency Safety:
     - Row-level SELECT ... FOR UPDATE locking.
     - Deterministic ascending lock acquisition order (Seat.id.asc()) to prevent deadlocks.
     - PostgreSQL SET LOCAL lock_timeout = '2s' to fail-fast under heavy contention (HTTP 503).
  2. Hold Lifecycle:
     - 5-minute temporary hold duration.
     - 1-4 seats per hold request.
     - Maximum 4 confirmed/held seats per student per event.
     - Single active hold per student: new hold atomically replaces any previous hold.
     - Expired holds are automatically released to available status.
  3. All-or-Nothing Guarantee:
     - Transactions ensure that all requested seats are successfully claimed or none are.
     - Any conflict immediately rolls back the transaction with HTTP 409 Conflict.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingSeat, BookingStatus
from app.models.event import Event
from app.models.hold import Hold, HoldSeat
from app.models.seat import Seat, SeatStatus
from app.schemas.booking import SeatMapResponse, SeatResponse
from app.services.audit_service import log_audit

# Default configuration constants
HOLD_DURATION_MINUTES = 5
MAX_SEATS_PER_STUDENT = 4


def release_expired_holds(db: Session, event_id: uuid.UUID | None = None) -> int:
    """
    Find and release all expired holds across the system or for a specific event.
    Reverts seats back to AVAILABLE status and deletes the Hold record.
    Returns the number of expired holds released.
    """
    now_utc = datetime.now(timezone.utc)
    query = db.query(Hold).filter(Hold.expires_at <= now_utc)
    if event_id:
        query = query.filter(Hold.event_id == event_id)

    expired_holds = query.all()
    count = len(expired_holds)

    for hold in expired_holds:
        # Revert associated seats back to AVAILABLE if still in HELD state
        for hs in hold.hold_seats:
            db.query(Seat).filter(
                Seat.id == hs.seat_id,
                Seat.status == SeatStatus.HELD,
            ).update({"status": SeatStatus.AVAILABLE})
        db.delete(hold)

    if count > 0:
        db.commit()

    return count


def get_seat_map(
    db: Session,
    event_id: uuid.UUID,
    current_user_id: uuid.UUID | None = None,
) -> SeatMapResponse:
    """
    Retrieve the venue seat map and status for an event.
    Automatically releases any expired holds before querying.
    """
    # 1. Verify event exists
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with id '{event_id}' not found",
        )

    # 2. Release expired holds for this event to ensure clean seat availability
    release_expired_holds(db, event_id=event_id)

    # 3. Retrieve all seats for this event
    seats = (
        db.query(Seat)
        .filter(Seat.event_id == event_id)
        .order_by(Seat.seat_number.asc())
        .all()
    )

    # 4. Check seats currently held by this user
    user_held_seat_ids = set()
    if current_user_id:
        now_utc = datetime.now(timezone.utc)
        user_hold = (
            db.query(Hold)
            .filter(
                Hold.user_id == current_user_id,
                Hold.event_id == event_id,
                Hold.expires_at > now_utc,
            )
            .first()
        )
        if user_hold:
            user_held_seat_ids = {hs.seat_id for hs in user_hold.hold_seats}

    # 5. Format seat responses and tally totals
    seat_responses = []
    available_count = 0
    held_count = 0
    booked_count = 0

    for s in seats:
        if s.status == SeatStatus.AVAILABLE:
            available_count += 1
        elif s.status == SeatStatus.HELD:
            held_count += 1
        elif s.status == SeatStatus.BOOKED:
            booked_count += 1

        seat_responses.append(
            SeatResponse(
                id=s.id,
                event_id=s.event_id,
                seat_number=s.seat_number,
                status=s.status,
                is_held_by_me=(s.id in user_held_seat_ids),
            )
        )

    return SeatMapResponse(
        event_id=event.id,
        total_seats=event.total_seats,
        available_count=available_count,
        held_count=held_count,
        booked_count=booked_count,
        seats=seat_responses,
    )


def hold_seats(
    db: Session,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    seat_numbers: list[str],
) -> Hold:
    """
    Atomically acquire a 5-minute temporary hold on 1-4 requested seats.

    Guarantees:
      - Row-level SELECT ... FOR UPDATE locking.
      - Stable ascending lock order (Seat.id.asc()) to eliminate deadlocks.
      - Lock timeout of 2 seconds (returns HTTP 503 under heavy contention).
      - Server-side enforcement of 1-4 seats and maximum 4 total per student.
      - Replaces student's previous active hold on the same event.
      - All-or-nothing: if any seat is unavailable, transaction rolls back with HTTP 409.
    """
    # 1. Input validations
    if not seat_numbers or len(seat_numbers) < 1 or len(seat_numbers) > MAX_SEATS_PER_STUDENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You must request between 1 and {MAX_SEATS_PER_STUDENT} seats per hold.",
        )

    # Check for duplicates in the request
    if len(seat_numbers) != len(set(seat_numbers)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate seat numbers provided in the reservation request.",
        )

    # 2. Set local PostgreSQL lock timeout (2s) to fail-fast on contention
    try:
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
    except Exception:
        pass  # Non-PostgreSQL fallbacks in testing

    # 3. Check event existence and booking closure time
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with id '{event_id}' not found",
        )

    now_utc = datetime.now(timezone.utc)
    if now_utc >= event.booking_close_time or now_utc >= event.start_time:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking is closed for this event.",
        )

    # 4. Check user limits: total confirmed seats + requested seats <= 4
    confirmed_seat_count = (
        db.query(func.count(BookingSeat.seat_id))
        .join(Booking, BookingSeat.booking_id == Booking.id)
        .filter(
            Booking.user_id == user_id,
            Booking.event_id == event_id,
            Booking.status == BookingStatus.CONFIRMED,
        )
        .scalar()
        or 0
    )

    if confirmed_seat_count + len(seat_numbers) > MAX_SEATS_PER_STUDENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Booking limit exceeded: You already have {confirmed_seat_count} confirmed seat(s). "
                f"Maximum allowed is {MAX_SEATS_PER_STUDENT} seats per student per event."
            ),
        )

    # 5. Check if the user already has a previous hold for this event
    # A student can have only ONE active hold per event. A new hold replaces it.
    previous_hold = (
        db.query(Hold)
        .filter(Hold.user_id == user_id, Hold.event_id == event_id)
        .first()
    )
    previous_held_seat_ids = set()
    if previous_hold:
        previous_held_seat_ids = {hs.seat_id for hs in previous_hold.hold_seats}

    # 6. Lock requested seats in STABLE ASCENDING ORDER (Seat.id.asc())
    # Deterministic lock ordering guarantees no circular wait deadlock between transactions.
    try:
        locked_seats = (
            db.query(Seat)
            .filter(
                Seat.event_id == event_id,
                Seat.seat_number.in_(seat_numbers),
            )
            .order_by(Seat.id.asc())
            .with_for_update()
            .all()
        )
    except OperationalError as exc:
        db.rollback()
        err_msg = str(exc).lower()
        if "lock timeout" in err_msg or "55p03" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database lock timeout: Server is busy under heavy contention. Please retry.",
            )
        raise

    if len(locked_seats) != len(seat_numbers):
        found_labels = {s.seat_number for s in locked_seats}
        missing_labels = list(set(seat_numbers) - found_labels)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Seat(s) {missing_labels} do not exist for this event.",
        )

    # 7. Check availability of all requested seats inside the locked transaction
    for seat in locked_seats:
        if seat.status == SeatStatus.BOOKED:
            db.rollback()
            log_audit(
                db=db,
                action="SEAT_HOLD_REJECTED",
                actor_id=user_id,
                actor_role="student",
                event_id=event_id,
                details={
                    "seat_numbers": seat_numbers,
                    "failed_seat": seat.seat_number,
                    "reason": "already_booked",
                },
                commit=True,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Seat '{seat.seat_number}' is already booked.",
            )

        if seat.status == SeatStatus.HELD:
            # If held by this user's own previous hold being replaced, it is allowed
            if previous_hold and seat.id in previous_held_seat_ids:
                continue

            # Check if the holding record is still active or expired
            active_hold = (
                db.query(Hold)
                .join(HoldSeat, Hold.id == HoldSeat.hold_id)
                .filter(
                    HoldSeat.seat_id == seat.id,
                    Hold.expires_at > now_utc,
                )
                .first()
            )
            if active_hold:
                db.rollback()
                log_audit(
                    db=db,
                    action="SEAT_HOLD_REJECTED",
                    actor_id=user_id,
                    actor_role="student",
                    event_id=event_id,
                    details={
                        "seat_numbers": seat_numbers,
                        "failed_seat": seat.seat_number,
                        "reason": "held_by_other_user",
                    },
                    commit=True,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Seat '{seat.seat_number}' is currently held by another user.",
                )
            else:
                # The hold on this seat has expired; we can claim it
                pass

    # 8. Release seats from the previous hold that are not in the new hold
    locked_seat_ids = {s.id for s in locked_seats}
    if previous_hold:
        for old_seat_id in previous_held_seat_ids:
            if old_seat_id not in locked_seat_ids:
                db.query(Seat).filter(
                    Seat.id == old_seat_id,
                    Seat.status == SeatStatus.HELD,
                ).update({"status": SeatStatus.AVAILABLE})
        db.delete(previous_hold)
        db.flush()

    # 9. Create the new Hold record (5 minutes duration)
    expires_at = now_utc + timedelta(minutes=HOLD_DURATION_MINUTES)
    new_hold = Hold(
        user_id=user_id,
        event_id=event_id,
        expires_at=expires_at,
    )
    db.add(new_hold)
    db.flush()

    # 10. Link seats and update status to HELD
    for seat in locked_seats:
        hold_seat = HoldSeat(hold_id=new_hold.id, seat_id=seat.id)
        db.add(hold_seat)
        seat.status = SeatStatus.HELD

    # 11. Record SEAT_HOLD audit entry in event shard
    log_audit(
        db=db,
        action="SEAT_HOLD",
        actor_id=user_id,
        actor_role="student",
        event_id=event_id,
        details={
            "hold_id": str(new_hold.id),
            "seat_numbers": seat_numbers,
            "expires_at": expires_at.isoformat(),
        },
        commit=False,
    )

    db.commit()
    db.refresh(new_hold)
    return new_hold


def confirm_hold(
    db: Session,
    user_id: uuid.UUID,
    hold_id: uuid.UUID,
) -> Booking:
    """
    Atomically convert an active, unexpired hold into a confirmed booking.

    Validates:
      - Hold exists and belongs to the calling user.
      - Hold has not expired.
      - Locks all held seats and transitions them to BOOKED status.
      - Deletes the hold atomically to prevent double confirmation.
    """
    try:
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
    except Exception:
        pass

    # 1. Query hold with row-level lock
    hold = db.query(Hold).filter(Hold.id == hold_id).with_for_update().first()
    if not hold:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hold with id '{hold_id}' not found.",
        )

    # 2. Verify ownership
    if hold.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: You can only confirm your own reservations.",
        )

    # 3. Verify expiry
    now_utc = datetime.now(timezone.utc)
    if hold.expires_at <= now_utc:
        # Expired: release held seats and remove hold
        for hs in hold.hold_seats:
            db.query(Seat).filter(
                Seat.id == hs.seat_id,
                Seat.status == SeatStatus.HELD,
            ).update({"status": SeatStatus.AVAILABLE})
        db.delete(hold)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your hold has expired. Please select seats and hold them again.",
        )

    # 4. Lock held seats in ascending order
    seat_ids = [hs.seat_id for hs in hold.hold_seats]
    locked_seats = (
        db.query(Seat)
        .filter(Seat.id.in_(seat_ids))
        .order_by(Seat.id.asc())
        .with_for_update()
        .all()
    )

    # 5. Verify all seats are in HELD state
    for seat in locked_seats:
        if seat.status != SeatStatus.HELD:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Seat '{seat.seat_number}' is no longer in held status.",
            )

    # 6. Create confirmed Booking record
    booking = Booking(
        user_id=user_id,
        event_id=hold.event_id,
        status=BookingStatus.CONFIRMED,
    )
    db.add(booking)
    db.flush()

    # 7. Transition seats to BOOKED and create BookingSeat join records
    for seat in locked_seats:
        bs = BookingSeat(booking_id=booking.id, seat_id=seat.id)
        db.add(bs)
        seat.status = SeatStatus.BOOKED

    # 8. Delete the Hold record (cascades to HoldSeat)
    db.delete(hold)

    # 9. Record BOOKING_CONFIRMED audit entry
    log_audit(
        db=db,
        action="BOOKING_CONFIRMED",
        actor_id=user_id,
        actor_role="student",
        event_id=hold.event_id,
        details={
            "booking_id": str(booking.id),
            "hold_id": str(hold_id),
            "seat_numbers": [s.seat_number for s in locked_seats],
        },
        commit=False,
    )

    db.commit()
    db.refresh(booking)
    return booking


def cancel_booking(
    db: Session,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    is_admin_or_organizer: bool = False,
) -> Booking:
    """
    Cancel an existing booking and release all its seats back to AVAILABLE.
    Enforces authorization: students can only cancel their own bookings.
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

    # 2. Authorization check
    if booking.user_id != user_id and not is_admin_or_organizer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: You cannot cancel another user's booking.",
        )

    # 3. Check already cancelled
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This booking has already been cancelled.",
        )

    # 4. Lock associated seats in ascending order
    seat_ids = [bs.seat_id for bs in booking.booking_seats]
    locked_seats = (
        db.query(Seat)
        .filter(Seat.id.in_(seat_ids))
        .order_by(Seat.id.asc())
        .with_for_update()
        .all()
    )

    # 5. Release seats back to AVAILABLE
    for seat in locked_seats:
        seat.status = SeatStatus.AVAILABLE

    # 6. Mark booking as CANCELLED (soft delete maintains audit history)
    booking.status = BookingStatus.CANCELLED

    # 7. Record BOOKING_CANCELLED audit entry
    actor_role = "student" if not is_admin_or_organizer else "organizer"
    log_audit(
        db=db,
        action="BOOKING_CANCELLED",
        actor_id=user_id,
        actor_role=actor_role,
        event_id=booking.event_id,
        details={
            "booking_id": str(booking.id),
            "seat_numbers": [s.seat_number for s in locked_seats],
        },
        commit=False,
    )

    db.commit()
    db.refresh(booking)
    return booking


def list_my_bookings(db: Session, user_id: uuid.UUID) -> list[Booking]:
    """Retrieve all bookings made by the current user."""
    return (
        db.query(Booking)
        .filter(Booking.user_id == user_id)
        .order_by(Booking.created_at.desc())
        .all()
    )


def get_booking_details(
    db: Session,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    is_admin_or_organizer: bool = False,
) -> Booking:
    """Retrieve details for a single booking, enforcing ownership."""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking with id '{booking_id}' not found.",
        )

    if booking.user_id != user_id and not is_admin_or_organizer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: You cannot view another user's booking.",
        )

    return booking
