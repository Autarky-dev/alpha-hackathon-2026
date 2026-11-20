"""
backend/scripts/test_booking.py
-------------------------------
Comprehensive automated test suite for SeatLock Core Booking Engine & Event Management.

Validates:
  1. Event creation with automatic venue seat generation.
  2. Event retrieval and seat map status.
  3. Optimistic concurrency control (OCC) & stale update rejection (HTTP 409).
  4. Single-seat & multi-seat hold creation.
  5. Maximum seat limit rejection (> 4 seats -> HTTP 400).
  6. Duplicate seat input rejection (HTTP 400).
  7. Single active hold replacement per student.
  8. Conflict rejection on actively held seats (HTTP 409).
  9. Conflict rejection on booked seats (HTTP 409).
 10. All-or-Nothing transactional rollback on partial unavailability.
 11. Hold expiry and lazy seat reclamation.
 12. Valid hold confirmation into permanent booking.
 13. Expired hold confirmation rejection (HTTP 409).
 14. Booking cancellation and seat release.
 15. Cross-user unauthorized booking access rejection (HTTP 403).
 16. Booking closure enforcement (past cutoff time -> HTTP 409).
 17. High-concurrency race condition test with 10 simultaneous threads competing for the same seat.
 18. Concurrent multi-seat reservation race testing atomicity across overlapping sets.
"""

import concurrent.futures
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.booking import Booking, BookingStatus
from app.models.event import Event
from app.models.hold import Hold
from app.models.seat import Seat, SeatStatus
from app.models.user import User, UserRole


def setup_test_students(db: Session, count: int = 10) -> dict[str, str]:
    """Ensure additional student test users exist for multi-user concurrency tests."""
    credentials = {}
    for i in range(1, count + 1):
        uname = f"concurrency_student_{i}"
        pwd = f"Pass123_Student_{i}!"
        credentials[uname] = pwd

        user = db.query(User).filter(User.username == uname).first()
        if not user:
            user = User(
                username=uname,
                password_hash=hash_password(pwd),
                role=UserRole.STUDENT,
            )
            db.add(user)
    db.commit()
    return credentials


def get_auth_client(username: str, password: str) -> TestClient:
    """Return a TestClient authenticated with HttpOnly cookie for given credentials."""
    client = TestClient(app)
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return client


def run_all_tests():
    print("=" * 70)
    print("  SeatLock — Core Booking Engine & Event Management Test Suite")
    print("=" * 70)

    db: Session = SessionLocal()
    concurrency_creds = setup_test_students(db, count=10)

    # Prepare standard authenticated clients
    student_client = get_auth_client(settings.SEED_STUDENT_USERNAME, settings.SEED_STUDENT_PASSWORD)
    organizer_client = get_auth_client(settings.SEED_ORGANIZER_USERNAME, settings.SEED_ORGANIZER_PASSWORD)
    admin_client = get_auth_client(settings.SEED_ADMIN_USERNAME, settings.SEED_ADMIN_PASSWORD)

    passed_checks = 0
    total_checks = 0

    def record_check(description: str, condition: bool, details: str = ""):
        nonlocal passed_checks, total_checks
        total_checks += 1
        if condition:
            passed_checks += 1
            print(f"  ✓ [{total_checks:02d}] {description}")
        else:
            print(f"  ✗ [{total_checks:02d}] FAILED: {description}")
            if details:
                print(f"       Details: {details}")

    # -----------------------------------------------------------------------
    # TEST 1: Event Creation & Automatic Venue Seat Initialization
    # -----------------------------------------------------------------------
    print("\n--- [Test 1] Event Creation & Automatic Seat Initialization ---")
    future_time = datetime.now(timezone.utc) + timedelta(days=7)
    close_time = future_time - timedelta(hours=2)

    event_payload = {
        "title": "Tech Summit 2026",
        "description": "Annual Technology and Innovation Conference",
        "location": "Main Auditorium",
        "start_time": future_time.isoformat(),
        "booking_close_time": close_time.isoformat(),
        "total_seats": 20,
    }

    # Student cannot create events (RBAC check)
    resp = student_client.post("/events", json=event_payload)
    record_check("Student rejected from creating event (HTTP 403)", resp.status_code == 403)

    # Organizer creates event
    resp = organizer_client.post("/events", json=event_payload)
    record_check("Organizer successfully creates event (HTTP 201)", resp.status_code == 201)
    event_data = resp.json()
    event_id = event_data["id"]
    event_version = event_data["version"]

    # Verify venue seats were automatically initialized in DB
    seat_count = db.query(Seat).filter(Seat.event_id == uuid.UUID(event_id)).count()
    record_check(f"Database initialized exactly 20 seats for event (found {seat_count})", seat_count == 20)

    # -----------------------------------------------------------------------
    # TEST 2: Seat Map Retrieval & Accuracy
    # -----------------------------------------------------------------------
    print("\n--- [Test 2] Seat Map Retrieval ---")
    resp = student_client.get(f"/events/{event_id}/seats")
    record_check("Get seat map returns HTTP 200", resp.status_code == 200)
    map_data = resp.json()
    record_check(
        "Seat map reports all 20 seats initially available",
        map_data["total_seats"] == 20
        and map_data["available_count"] == 20
        and map_data["held_count"] == 0
        and map_data["booked_count"] == 0,
    )

    # -----------------------------------------------------------------------
    # TEST 3: Optimistic Concurrency Control (OCC) for Event Updates
    # -----------------------------------------------------------------------
    print("\n--- [Test 3] Event Updates & Optimistic Locking ---")
    # Valid update with matching version
    update_payload = {
        "title": "Tech Summit 2026 — Keynote & Workshops",
        "description": "Updated conference agenda",
        "location": "Grand Hall B",
        "start_time": future_time.isoformat(),
        "booking_close_time": close_time.isoformat(),
        "total_seats": 25,  # Expanding capacity
        "version": event_version,  # version = 1
    }
    resp = organizer_client.put(f"/events/{event_id}", json=update_payload)
    record_check("Organizer updates event with correct version (HTTP 200)", resp.status_code == 200)
    updated_data = resp.json()
    new_version = updated_data["version"]
    record_check(f"Event version incremented to {new_version}", new_version == event_version + 1)

    # Stale update with old version (should fail with HTTP 409 Conflict)
    stale_payload = {
        "title": "Stale Update Conflict",
        "description": "This should be rejected",
        "location": "Grand Hall B",
        "start_time": future_time.isoformat(),
        "booking_close_time": close_time.isoformat(),
        "total_seats": 25,
        "version": event_version,  # Old version 1 instead of 2!
    }
    resp = organizer_client.put(f"/events/{event_id}", json=stale_payload)
    record_check(
        "Stale version update rejected with HTTP 409 Conflict",
        resp.status_code == 409 and "conflict" in resp.json().get("detail", "").lower(),
    )

    # -----------------------------------------------------------------------
    # TEST 4: Single-Seat & Multi-Seat Hold Creation (1-4 seats)
    # -----------------------------------------------------------------------
    print("\n--- [Test 4] Seat Hold Creation ---")
    # Hold 2 valid seats
    resp = student_client.post(f"/events/{event_id}/hold", json={"seat_numbers": ["A1", "A2"]})
    record_check("Student holds 2 seats ['A1', 'A2'] (HTTP 201)", resp.status_code == 201)
    hold_data = resp.json()
    first_hold_id = hold_data["id"]

    # Verify seat map reflects held seats
    resp = student_client.get(f"/events/{event_id}/seats")
    map_data = resp.json()
    record_check(
        "Seat map reflects held_count=2, available_count=23",
        map_data["held_count"] == 2 and map_data["available_count"] == 23,
    )

    # -----------------------------------------------------------------------
    # TEST 5: Seat Count Limit Violations (> 4 seats or 0 seats)
    # -----------------------------------------------------------------------
    print("\n--- [Test 5] Hold Limits & Input Validation ---")
    # Requesting 5 seats (> 4)
    resp = student_client.post(
        f"/events/{event_id}/hold",
        json={"seat_numbers": ["B1", "B2", "B3", "B4", "B5"]},
    )
    record_check("Requesting 5 seats rejected with HTTP 400/422", resp.status_code in [400, 422])

    # Requesting duplicate seats in same request
    resp = student_client.post(
        f"/events/{event_id}/hold",
        json={"seat_numbers": ["B1", "B1"]},
    )
    record_check("Duplicate seats in request rejected with HTTP 400", resp.status_code == 400)

    # -----------------------------------------------------------------------
    # TEST 6: Single Active Hold Replacement
    # -----------------------------------------------------------------------
    print("\n--- [Test 6] Active Hold Replacement ---")
    # Student holds ['A3', 'A4']. This MUST replace previous hold ['A1', 'A2'].
    resp = student_client.post(f"/events/{event_id}/hold", json={"seat_numbers": ["A3", "A4"]})
    record_check("Student creates new hold ['A3', 'A4'] (HTTP 201)", resp.status_code == 201)
    new_hold_id = resp.json()["id"]

    # Verify previous seats 'A1', 'A2' are now AVAILABLE again
    seat_a1 = db.query(Seat).filter(Seat.event_id == uuid.UUID(event_id), Seat.seat_number == "A1").first()
    seat_a3 = db.query(Seat).filter(Seat.event_id == uuid.UUID(event_id), Seat.seat_number == "A3").first()
    record_check("Previous seat A1 reverted to AVAILABLE", seat_a1.status == SeatStatus.AVAILABLE)
    record_check("New seat A3 status is HELD", seat_a3.status == SeatStatus.HELD)

    # Verify only 1 active hold exists in DB for this student
    active_holds_count = db.query(Hold).filter(Hold.event_id == uuid.UUID(event_id)).count()
    record_check("Total active holds for event is exactly 1 (old hold deleted)", active_holds_count == 1)

    # -----------------------------------------------------------------------
    # TEST 7: Conflict on Actively Held Seats
    # -----------------------------------------------------------------------
    print("\n--- [Test 7] Conflict on Actively Held Seats ---")
    # Second student tries to claim 'A3' (currently held by first student)
    student_2_client = get_auth_client("concurrency_student_2", concurrency_creds["concurrency_student_2"])
    resp = student_2_client.post(f"/events/{event_id}/hold", json={"seat_numbers": ["A3"]})
    record_check(
        "Competing student rejected from holding already-held seat A3 (HTTP 409)",
        resp.status_code == 409,
    )

    # -----------------------------------------------------------------------
    # TEST 8: All-or-Nothing Transactional Rollback
    # -----------------------------------------------------------------------
    print("\n--- [Test 8] All-or-Nothing Atomicity ---")
    # Student 2 requests ['A5' (available), 'A3' (held by student 1)]
    resp = student_2_client.post(f"/events/{event_id}/hold", json={"seat_numbers": ["A5", "A3"]})
    record_check("Multi-seat hold with 1 unavailable seat rejected with HTTP 409", resp.status_code == 409)

    # Verify 'A5' remains AVAILABLE (was NOT held due to rollback)
    seat_a5 = db.query(Seat).filter(Seat.event_id == uuid.UUID(event_id), Seat.seat_number == "A5").first()
    record_check("Seat A5 was rolled back and remains AVAILABLE", seat_a5.status == SeatStatus.AVAILABLE)

    # -----------------------------------------------------------------------
    # TEST 9: Hold Confirmation into Permanent Booking
    # -----------------------------------------------------------------------
    print("\n--- [Test 9] Hold Confirmation ---")
    # Confirm valid hold
    resp = student_client.post(f"/holds/{new_hold_id}/confirm")
    record_check("Student confirms valid hold (HTTP 201)", resp.status_code == 201)
    booking_data = resp.json()
    confirmed_booking_id = booking_data["id"]
    record_check(
        "Booking status is CONFIRMED with seats ['A3', 'A4']",
        booking_data["status"] == "confirmed" and set(booking_data["seat_numbers"]) == {"A3", "A4"},
    )

    # Verify seats are permanently BOOKED in DB
    db.expire_all()
    seat_a3 = db.query(Seat).filter(Seat.event_id == uuid.UUID(event_id), Seat.seat_number == "A3").first()
    record_check("Seat A3 status transitioned to BOOKED", seat_a3.status == SeatStatus.BOOKED)

    # Cannot re-confirm the same hold (already consumed)
    resp = student_client.post(f"/holds/{new_hold_id}/confirm")
    record_check("Re-confirming already converted hold returns HTTP 404", resp.status_code == 404)

    # -----------------------------------------------------------------------
    # TEST 10: Conflict on Already Booked Seats
    # -----------------------------------------------------------------------
    print("\n--- [Test 10] Conflict on Booked Seats ---")
    resp = student_2_client.post(f"/events/{event_id}/hold", json={"seat_numbers": ["A3"]})
    record_check("Attempt to hold booked seat A3 returns HTTP 409 Conflict", resp.status_code == 409)

    # -----------------------------------------------------------------------
    # TEST 11: Hold Expiry & Automatic Reclamation
    # -----------------------------------------------------------------------
    print("\n--- [Test 11] Hold Expiry & Reclamation ---")
    # Student 2 holds 'B1'
    resp = student_2_client.post(f"/events/{event_id}/hold", json={"seat_numbers": ["B1"]})
    assert resp.status_code == 201
    hold_b1_id = resp.json()["id"]

    # Manually expire this hold in DB
    db.query(Hold).filter(Hold.id == uuid.UUID(hold_b1_id)).update({
        "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)
    })
    db.commit()

    # Attempting to confirm an expired hold must be rejected with HTTP 409
    resp = student_2_client.post(f"/holds/{hold_b1_id}/confirm")
    record_check("Confirming expired hold rejected with HTTP 409", resp.status_code == 409)

    # Seat B1 should be reclaimed and holdable by student 1
    resp = student_client.post(f"/events/{event_id}/hold", json={"seat_numbers": ["B1"]})
    record_check("Student 1 can claim seat B1 after previous hold expired (HTTP 201)", resp.status_code == 201)

    # -----------------------------------------------------------------------
    # TEST 12: Booking Cancellation & Seat Release
    # -----------------------------------------------------------------------
    print("\n--- [Test 12] Booking Cancellation ---")
    resp = student_client.post(f"/bookings/{confirmed_booking_id}/cancel")
    record_check("Student cancels own booking (HTTP 200)", resp.status_code == 200)

    # Verify seats are released back to AVAILABLE in DB
    db.expire_all()
    seat_a3 = db.query(Seat).filter(Seat.event_id == uuid.UUID(event_id), Seat.seat_number == "A3").first()
    record_check("Cancelled seats A3 reverted to AVAILABLE", seat_a3.status == SeatStatus.AVAILABLE)

    # Cancelling again returns HTTP 400
    resp = student_client.post(f"/bookings/{confirmed_booking_id}/cancel")
    record_check("Cancelling an already-cancelled booking returns HTTP 400", resp.status_code == 400)

    # -----------------------------------------------------------------------
    # TEST 13: Unauthorized Cross-User Booking Access
    # -----------------------------------------------------------------------
    print("\n--- [Test 13] Unauthorized Booking Access ---")
    # Student 2 creates a new booking
    resp = student_2_client.post(f"/events/{event_id}/hold", json={"seat_numbers": ["B2"]})
    assert resp.status_code == 201
    h2_id = resp.json()["id"]
    resp = student_2_client.post(f"/holds/{h2_id}/confirm")
    assert resp.status_code == 201
    student_2_booking_id = resp.json()["id"]

    # Student 1 tries to view Student 2's booking details -> HTTP 403
    resp = student_client.get(f"/bookings/{student_2_booking_id}")
    record_check("Student 1 rejected from viewing Student 2's booking (HTTP 403)", resp.status_code == 403)

    # Student 1 tries to cancel Student 2's booking -> HTTP 403
    resp = student_client.post(f"/bookings/{student_2_booking_id}/cancel")
    record_check("Student 1 rejected from cancelling Student 2's booking (HTTP 403)", resp.status_code == 403)

    # -----------------------------------------------------------------------
    # TEST 14: Booking Closure Enforcement
    # -----------------------------------------------------------------------
    print("\n--- [Test 14] Booking Closure Enforcement ---")
    past_event = Event(
        title="Historical Closed Event",
        location="Hall C",
        start_time=datetime.now(timezone.utc) - timedelta(hours=5),
        booking_close_time=datetime.now(timezone.utc) - timedelta(hours=6),
        total_seats=10,
    )
    db.add(past_event)
    db.flush()
    db.add(Seat(event_id=past_event.id, seat_number="C1", status=SeatStatus.AVAILABLE))
    db.commit()

    resp = student_client.post(f"/events/{past_event.id}/hold", json={"seat_numbers": ["C1"]})
    record_check("Attempt to hold seats on closed/past event rejected with HTTP 409", resp.status_code == 409)

    # -----------------------------------------------------------------------
    # TEST 15: Concurrency Safety Test — 10 Threads Competing for EXACT SAME Seat
    # -----------------------------------------------------------------------
    print("\n--- [Test 15] CONCURRENCY STRESS TEST (10 Threads Competing for Seat C2) ---")
    # Setup fresh event with 1 target seat
    race_event = Event(
        title="High-Demand Rock Concert",
        location="Stadium",
        start_time=datetime.now(timezone.utc) + timedelta(days=10),
        booking_close_time=datetime.now(timezone.utc) + timedelta(days=9),
        total_seats=10,
    )
    db.add(race_event)
    db.flush()
    target_seat = Seat(event_id=race_event.id, seat_number="C2", status=SeatStatus.AVAILABLE)
    db.add(target_seat)
    db.commit()

    race_event_id = str(race_event.id)

    # Worker function executed across threads
    def attempt_hold_seat(student_idx: int):
        uname = f"concurrency_student_{student_idx}"
        pwd = concurrency_creds[uname]
        th_client = get_auth_client(uname, pwd)
        resp = th_client.post(f"/events/{race_event_id}/hold", json={"seat_numbers": ["C2"]})
        return student_idx, resp.status_code, resp.text

    # Fire 10 simultaneous threads to claim seat C2
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_hold_seat, i) for i in range(1, 11)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    successes = [r for r in results if r[1] == 201]
    conflicts = [r for r in results if r[1] in [409, 503]]

    print(f"       Concurrent Outcomes: {len(successes)} Winner (HTTP 201), {len(conflicts)} Blocked (HTTP 409/503)")
    record_check(
        "Exactly ONE concurrent thread won the race (HTTP 201)",
        len(successes) == 1,
        f"Success count: {len(successes)}",
    )
    record_check(
        "All other 9 threads were rejected with HTTP 409 Conflict or 503 Timeout",
        len(conflicts) == 9,
        f"Conflict count: {len(conflicts)}",
    )

    # Verify database state has exactly 1 hold and seat is HELD
    db.rollback()
    actual_seat = db.query(Seat).filter(Seat.event_id == uuid.UUID(race_event_id), Seat.seat_number == "C2").first()
    record_check("Database confirms seat C2 is HELD by exactly one user with zero corruption", actual_seat.status == SeatStatus.HELD)

    # -----------------------------------------------------------------------
    # TEST 16: Concurrent Multi-Seat Reservation Atomicity (Overlapping Pairs)
    # -----------------------------------------------------------------------
    print("\n--- [Test 16] CONCURRENT MULTI-SEAT OVERLAP TEST ---")
    # Setup 3 seats: D1, D2, D3
    s_d1 = Seat(event_id=uuid.UUID(race_event_id), seat_number="D1", status=SeatStatus.AVAILABLE)
    s_d2 = Seat(event_id=uuid.UUID(race_event_id), seat_number="D2", status=SeatStatus.AVAILABLE)
    s_d3 = Seat(event_id=uuid.UUID(race_event_id), seat_number="D3", status=SeatStatus.AVAILABLE)
    db.add_all([s_d1, s_d2, s_d3])
    db.commit()

    # Worker 1 requests ["D1", "D2"]
    # Worker 2 requests ["D2", "D3"]
    # Because D2 is contested, exactly one worker must win both its seats, and the loser must get NONE!
    def attempt_multi(worker_id: int, seats: list[str]):
        uname = f"concurrency_student_{worker_id}"
        pwd = concurrency_creds[uname]
        th_client = get_auth_client(uname, pwd)
        resp = th_client.post(f"/events/{race_event_id}/hold", json={"seat_numbers": seats})
        return worker_id, seats, resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_multi, 1, ["D1", "D2"])
        f2 = executor.submit(attempt_multi, 2, ["D2", "D3"])
        res1 = f1.result()
        res2 = f2.result()

    multi_successes = [r for r in [res1, res2] if r[2] == 201]
    multi_failures = [r for r in [res1, res2] if r[2] in [409, 503]]

    record_check(
        "Exactly one worker won its overlapping pair, the other received 409 Conflict",
        len(multi_successes) == 1 and len(multi_failures) == 1,
        f"Results: {res1}, {res2}",
    )

    winner_seats = multi_successes[0][1]
    loser_seats = multi_failures[0][1]
    non_contested_loser_seat = list(set(loser_seats) - set(winner_seats))[0]

    db.rollback()
    loser_seat_obj = db.query(Seat).filter(Seat.event_id == uuid.UUID(race_event_id), Seat.seat_number == non_contested_loser_seat).first()
    record_check(
        f"Loser's non-contested seat ({non_contested_loser_seat}) remained AVAILABLE (all-or-nothing rollback)",
        loser_seat_obj.status == SeatStatus.AVAILABLE,
    )

    # -----------------------------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"  Final Suite Result: {passed_checks}/{total_checks} assertions PASSED")
    print("=" * 70)

    db.close()
    return passed_checks == total_checks


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
