"""
backend/scripts/seed_demo_data.py
---------------------------------
Safe, repeatable, and idempotent demo data seeder for SeatLock.

Responsibilities:
  - Ensures default demo users exist (student, organizer, admin).
  - Creates representative demo events with full venue seat layouts (if not already present).
  - Creates sample confirmed bookings and check-in records for immediate frontend UI testing.
  - GUARANTEED: Never drops, resets, or deletes existing database data. Safe to run repeatedly.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Add backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.booking import Booking, BookingSeat, BookingStatus
from app.models.event import Event
from app.models.seat import Seat, SeatStatus
from app.models.user import User, UserRole
from app.schemas.event import EventCreate
from app.services import event_service
try:
    from scripts.seed_users import seed_test_users
except ImportError:
    from backend.scripts.seed_users import seed_test_users


def seed_demo_data():
    print("=" * 65)
    print("  SeatLock — Demo Data Seeder (Safe & Idempotent)")
    print("=" * 65)

    # 1. Ensure test users are present
    seed_test_users()

    db: Session = SessionLocal()
    try:
        organizer = db.query(User).filter(User.username == settings.SEED_ORGANIZER_USERNAME).first()
        student = db.query(User).filter(User.username == settings.SEED_STUDENT_USERNAME).first()

        if not organizer or not student:
            print("  [error] Seeded users could not be found.")
            return

        now_utc = datetime.now(timezone.utc)

        # 2. Demo Event 1: Tech Summit (40 seats, rows A-D)
        summit_title = "SeatLock Hackathon Tech Summit 2026"
        event_summit = db.query(Event).filter(Event.title == summit_title).first()

        if not event_summit:
            create_payload = EventCreate(
                title=summit_title,
                description="Flagship annual developer summit exploring high-concurrency systems, security, and cloud architectures.",
                location="Main Auditorium Hall A, Silicon Campus",
                start_time=now_utc + timedelta(days=5),
                booking_close_time=now_utc + timedelta(days=4),
                total_seats=40,
            )
            event_summit = event_service.create_event(db, create_payload, creator=organizer)
            print(f"  [created] Event 1: '{summit_title}' (ID: {event_summit.id}, 40 seats)")
        else:
            print(f"  [exists]  Event 1: '{summit_title}' (ID: {event_summit.id})")

        # 3. Demo Event 2: Cloud Architecture Keynote (20 seats, rows A-B)
        keynote_title = "AI Systems & Resilient Database Keynote"
        event_keynote = db.query(Event).filter(Event.title == keynote_title).first()

        if not event_keynote:
            create_payload = EventCreate(
                title=keynote_title,
                description="Deep dive into PostgreSQL row-level locking, optimistic concurrency control, and shard partitioning.",
                location="Conference Center Hall 2",
                start_time=now_utc + timedelta(days=7),
                booking_close_time=now_utc + timedelta(days=6),
                total_seats=20,
            )
            event_keynote = event_service.create_event(db, create_payload, creator=organizer)
            print(f"  [created] Event 2: '{keynote_title}' (ID: {event_keynote.id}, 20 seats)")
        else:
            print(f"  [exists]  Event 2: '{keynote_title}' (ID: {event_keynote.id})")

        # 4. Sample Booking 1: Confirmed and Already Checked In (Seat A1 on Tech Summit)
        existing_booking_1 = (
            db.query(Booking)
            .filter(Booking.user_id == student.id, Booking.event_id == event_summit.id)
            .first()
        )

        if not existing_booking_1:
            seat_a1 = db.query(Seat).filter(Seat.event_id == event_summit.id, Seat.seat_number == "A1").first()
            if seat_a1 and seat_a1.status == SeatStatus.AVAILABLE:
                booking_1 = Booking(
                    user_id=student.id,
                    event_id=event_summit.id,
                    status=BookingStatus.CONFIRMED,
                    checked_in_at=now_utc - timedelta(hours=1),
                )
                db.add(booking_1)
                db.flush()

                bs_1 = BookingSeat(
                    booking_id=booking_1.id,
                    seat_id=seat_a1.id,
                    checked_in_at=now_utc - timedelta(hours=1),
                )
                db.add(bs_1)
                seat_a1.status = SeatStatus.BOOKED

                db.commit()
                print(f"  [created] Sample Booking 1 (Checked-in): Student on Seat A1 (Booking ID: {booking_1.id})")
        else:
            print(f"  [exists]  Sample Booking 1: (Booking ID: {existing_booking_1.id})")

        # 5. Sample Booking 2: Confirmed, Pending Check-In (Seats A2, A3 on Keynote)
        existing_booking_2 = (
            db.query(Booking)
            .filter(Booking.user_id == student.id, Booking.event_id == event_keynote.id)
            .first()
        )

        if not existing_booking_2:
            seat_k2 = db.query(Seat).filter(Seat.event_id == event_keynote.id, Seat.seat_number == "A2").first()
            seat_k3 = db.query(Seat).filter(Seat.event_id == event_keynote.id, Seat.seat_number == "A3").first()
            if seat_k2 and seat_k3 and seat_k2.status == SeatStatus.AVAILABLE and seat_k3.status == SeatStatus.AVAILABLE:
                booking_2 = Booking(
                    user_id=student.id,
                    event_id=event_keynote.id,
                    status=BookingStatus.CONFIRMED,
                    checked_in_at=None,
                )
                db.add(booking_2)
                db.flush()

                bs_2a = BookingSeat(booking_id=booking_2.id, seat_id=seat_k2.id)
                bs_2b = BookingSeat(booking_id=booking_2.id, seat_id=seat_k3.id)
                db.add_all([bs_2a, bs_2b])

                seat_k2.status = SeatStatus.BOOKED
                seat_k3.status = SeatStatus.BOOKED

                db.commit()
                print(f"  [created] Sample Booking 2 (Pending Check-in): Student on Seats A2, A3 (Booking ID: {booking_2.id})")
        else:
            print(f"  [exists]  Sample Booking 2: (Booking ID: {existing_booking_2.id})")

        print("=" * 65)
        print("  ✓ Demo data preparation completed safely and successfully.")
        print("=" * 65)

    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
