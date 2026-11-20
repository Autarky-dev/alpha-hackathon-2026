"""
backend/app/services/hold_cleaner.py
------------------------------------
Background periodic task for automatic seat hold expiration.

Safety & Concurrency Design:
  1. Row-Level Locking with SKIP LOCKED:
     - Uses `with_for_update(skip_locked=True)` on expired holds to prevent blocking
       active confirmation or hold creation requests.
  2. Guarded Seat Release:
     - Before resetting any seat back to AVAILABLE, verifies that the seat does not
       belong to a confirmed booking or another active hold.
  3. Transactional Audit:
     - Every expired hold releases its seats and logs `HOLD_EXPIRED` to the event's
       corresponding audit shard within the same database transaction.
  4. Non-Blocking Async Scheduler:
     - Runs on an asyncio background loop managed by FastAPI lifespan events.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.booking import Booking, BookingSeat, BookingStatus
from app.models.hold import Hold, HoldSeat
from app.models.seat import Seat, SeatStatus
from app.services.audit_service import log_audit

logger = logging.getLogger("seatlock.hold_cleaner")

# Global handle for the background task
_cleaner_task: asyncio.Task | None = None
_shutdown_event: asyncio.Event | None = None


def sweep_expired_holds(db: Session) -> int:
    """
    Safely sweep and release all expired holds across the database.

    Guarantees:
      - Never overwrites confirmed bookings or unexpired active holds.
      - Uses row locking to avoid race conditions.
      - Records HOLD_EXPIRED audit event in the appropriate shard.
    """
    now_utc = datetime.now(timezone.utc)
    try:
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
    except Exception:
        pass

    # 1. Query expired holds with skip_locked to avoid blocking active user operations
    expired_holds = (
        db.query(Hold)
        .filter(Hold.expires_at <= now_utc)
        .with_for_update(skip_locked=True)
        .all()
    )

    if not expired_holds:
        return 0

    released_count = 0

    for hold in expired_holds:
        event_id = hold.event_id
        user_id = hold.user_id
        hold_id = hold.id

        # 2. Collect seats belonging to this hold
        seat_ids = [hs.seat_id for hs in hold.hold_seats]

        if seat_ids:
            # Lock seats in stable ascending order
            locked_seats = (
                db.query(Seat)
                .filter(Seat.id.in_(seat_ids))
                .order_by(Seat.id.asc())
                .with_for_update(skip_locked=True)
                .all()
            )

            released_seat_numbers = []

            for seat in locked_seats:
                # SAFETY CHECK 1: Ensure seat is not already confirmed in a booking
                is_booked = (
                    db.query(BookingSeat)
                    .join(Booking, BookingSeat.booking_id == Booking.id)
                    .filter(
                        BookingSeat.seat_id == seat.id,
                        Booking.status == BookingStatus.CONFIRMED,
                    )
                    .first()
                )
                if is_booked:
                    continue  # Do not release booked seat!

                # SAFETY CHECK 2: Ensure seat is not part of another active (unexpired) hold
                has_active_hold = (
                    db.query(HoldSeat)
                    .join(Hold, HoldSeat.hold_id == Hold.id)
                    .filter(
                        HoldSeat.seat_id == seat.id,
                        Hold.id != hold_id,
                        Hold.expires_at > now_utc,
                    )
                    .first()
                )
                if has_active_hold:
                    continue  # Covered by another valid hold!

                # Safe to revert to AVAILABLE
                if seat.status == SeatStatus.HELD:
                    seat.status = SeatStatus.AVAILABLE
                    released_seat_numbers.append(seat.seat_number)

            # 3. Log audit event to event's shard
            log_audit(
                db=db,
                action="HOLD_EXPIRED",
                actor_id=user_id,
                actor_role="student",
                event_id=event_id,
                details={
                    "hold_id": str(hold_id),
                    "released_seats": released_seat_numbers,
                    "expired_at": now_utc.isoformat(),
                },
                commit=False,
            )

        # 4. Delete the expired Hold record (cascades to HoldSeat)
        db.delete(hold)
        released_count += 1

    db.commit()
    return released_count


async def run_hold_cleaner_loop(interval_seconds: int = 10):
    """Asynchronous background loop that periodically sweeps expired holds."""
    logger.info("[hold_cleaner] Background hold expiration worker started.")
    global _shutdown_event

    while _shutdown_event and not _shutdown_event.is_set():
        db: Session = SessionLocal()
        try:
            cleaned = sweep_expired_holds(db)
            if cleaned > 0:
                logger.info(f"[hold_cleaner] Released {cleaned} expired hold(s).")
        except Exception as exc:
            db.rollback()
            logger.error(f"[hold_cleaner] Error during hold sweep: {exc}")
        finally:
            db.close()

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break

    logger.info("[hold_cleaner] Background hold expiration worker stopped.")


def start_hold_cleaner(interval_seconds: int = 10) -> asyncio.Task:
    """Start the background cleaner task on the running event loop."""
    global _cleaner_task, _shutdown_event
    _shutdown_event = asyncio.Event()
    _cleaner_task = asyncio.create_task(run_hold_cleaner_loop(interval_seconds))
    return _cleaner_task


async def stop_hold_cleaner():
    """Gracefully signal and stop the background cleaner task."""
    global _cleaner_task, _shutdown_event
    if _shutdown_event:
        _shutdown_event.set()
    if _cleaner_task:
        _cleaner_task.cancel()
        try:
            await _cleaner_task
        except asyncio.CancelledError:
            pass
        _cleaner_task = None
