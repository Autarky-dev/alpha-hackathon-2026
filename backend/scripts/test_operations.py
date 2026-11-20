"""
backend/scripts/test_operations.py
----------------------------------
Comprehensive verification suite for SeatLock Remaining Backend Operations:
  1. Audit Logging & 4-Shard Hash Partitioning (audit_logs_0..3).
  2. Background Seat Hold Expiration Worker (SKIP LOCKED & audit integration).
  3. Check-In Backend, QR Ticket Cryptography, and Duplicate Prevention.
  4. Organizer Operations, Ownership Enforcement, and Attendee Manifests.
  5. Live FastAPI API Endpoints integration via TestClient.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.audit import AuditLog0, AuditLog1, AuditLog2, AuditLog3
from app.models.booking import Booking, BookingSeat, BookingStatus
from app.models.event import Event
from app.models.hold import Hold, HoldSeat
from app.models.seat import Seat, SeatStatus
from app.models.user import User, UserRole
from app.schemas.checkin import CheckInRequest
from app.schemas.event import EventCreate, EventUpdate
from app.services import audit_service, booking_service, checkin_service, event_service
from app.services.hold_cleaner import sweep_expired_holds


def get_or_create_user(db: Session, username: str, role: UserRole, password: str = "TestPass123!") -> User:
    """Helper to ensure a user exists with the requested role."""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def run_tests():
    print("=" * 70)
    print("SeatLock Remaining Operations Verification Suite")
    print("=" * 70)

    db: Session = SessionLocal()
    client = TestClient(app)
    assertions_passed = 0

    try:
        # Setup required actors
        admin = get_or_create_user(db, "admin_user", UserRole.ADMIN)
        student = get_or_create_user(db, "student_user", UserRole.STUDENT)
        org_a = get_or_create_user(db, "organizer_alpha", UserRole.ORGANIZER)
        org_b = get_or_create_user(db, "organizer_beta", UserRole.ORGANIZER)

        print(f"[setup] Actors verified: Admin={admin.username}, OrgA={org_a.username}, OrgB={org_b.username}, Student={student.username}")

        # =====================================================================
        # PART 1: AUDIT LOGGING & 4-SHARD HASH PARTITIONING
        # =====================================================================
        print("\n--- Part 1: Audit Logging & 4-Shard Hash Partitioning ---")

        # 1. Verify shard index calculation
        sample_uuids = [
            uuid.UUID("00000000-0000-0000-0000-000000000000"), # 0 % 4 == 0
            uuid.UUID("00000000-0000-0000-0000-000000000001"), # 1 % 4 == 1
            uuid.UUID("00000000-0000-0000-0000-000000000002"), # 2 % 4 == 2
            uuid.UUID("00000000-0000-0000-0000-000000000003"), # 3 % 4 == 3
        ]

        for expected_shard, test_uid in enumerate(sample_uuids):
            calc_shard = audit_service.get_shard_index(event_id=test_uid)
            assert calc_shard == expected_shard, f"Expected shard {expected_shard}, got {calc_shard}"
            assertions_passed += 1

        print(f"  [pass] Shard index mathematical routing (int(UUID) % 4) verified.")

        # 2. Write to each shard deterministically
        test_entries = []
        for expected_shard, test_uid in enumerate(sample_uuids):
            action_name = f"TEST_ACTION_SHARD_{expected_shard}_{uuid.uuid4().hex[:6]}"
            entry = audit_service.log_audit(
                db=db,
                action=action_name,
                actor_id=admin.id,
                actor_role=admin.role.value,
                event_id=test_uid,
                details={
                    "test_shard": expected_shard,
                    "password": "SHOULD_BE_REMOVED",
                    "jwt": "SECRET_JWT_REMOVED",
                    "safe_key": "safe_value",
                },
                commit=True,
            )
            test_entries.append((expected_shard, test_uid, action_name))

            # Verify physical write directly to the expected table
            ShardModel = audit_service.SHARDS[expected_shard]
            written = db.query(ShardModel).filter(ShardModel.action == action_name).first()
            assert written is not None, f"Entry not found in table audit_logs_{expected_shard}!"
            assert "password" not in written.details, "Sensitive credential was not sanitized!"
            assert "jwt" not in written.details, "Sensitive token was not sanitized!"
            assert written.details.get("safe_key") == "safe_value"
            assertions_passed += 3

        print(f"  [pass] Verified physical writes to audit_logs_0..3 with sensitive credential sanitization.")

        # 3. Test single-shard direct query
        target_shard, target_eid, target_action = test_entries[1] # Shard 1
        shard1_entries, count = audit_service.query_audit_logs(db, event_id=target_eid, action=target_action)
        assert count == 1, f"Expected 1 entry, got {count}"
        assert shard1_entries[0]["action"] == target_action
        assert shard1_entries[0]["shard_id"] == 1
        assertions_passed += 2
        print(f"  [pass] Single-shard direct query scanned shard {target_shard} with count={count}.")

        # 4. Test multi-shard federated query (UNION ALL)
        all_entries, total_count = audit_service.query_audit_logs(db, limit=10, offset=0)
        assert total_count >= 4, f"Expected total_count >= 4, got {total_count}"
        assert len(all_entries) <= 10
        # Verify pagination limit/offset
        page2_entries, p2_total = audit_service.query_audit_logs(db, limit=2, offset=1)
        assert len(page2_entries) == 2
        assert p2_total == total_count
        assertions_passed += 3
        print(f"  [pass] Multi-shard UNION ALL federated query returned {total_count} total entries with pagination.")

        # =====================================================================
        # PART 2: BACKGROUND HOLD EXPIRATION CLEANER
        # =====================================================================
        print("\n--- Part 2: Background Hold Expiration Worker ---")

        # 1. Create an event for expiration testing
        cleaner_event_data = EventCreate(
            title=f"Cleaner Test Venue {uuid.uuid4().hex[:6]}",
            location="Room 101",
            start_time=datetime.now(timezone.utc) + timedelta(days=2),
            booking_close_time=datetime.now(timezone.utc) + timedelta(days=1),
            total_seats=30,
        )
        cleaner_event = event_service.create_event(db, cleaner_event_data, creator=org_a)
        assertions_passed += 1

        # 2. Student holds seats A1, A2
        hold = booking_service.hold_seats(db, student.id, cleaner_event.id, ["A1", "A2"])
        assert hold is not None
        assertions_passed += 1

        # Check seats are HELD
        s_a1 = db.query(Seat).filter(Seat.event_id == cleaner_event.id, Seat.seat_number == "A1").first()
        s_a2 = db.query(Seat).filter(Seat.event_id == cleaner_event.id, Seat.seat_number == "A2").first()
        assert s_a1.status == SeatStatus.HELD
        assert s_a2.status == SeatStatus.HELD
        assertions_passed += 2

        # 3. Simulate passage of time by artificially aging expires_at
        hold.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.commit()

        # 4. Execute sweep_expired_holds
        swept = sweep_expired_holds(db)
        assert swept >= 1, f"Expected at least 1 hold swept, got {swept}"
        assertions_passed += 1

        # 5. Verify seats reverted to AVAILABLE
        db.refresh(s_a1)
        db.refresh(s_a2)
        assert s_a1.status == SeatStatus.AVAILABLE, f"Seat A1 was {s_a1.status}"
        assert s_a2.status == SeatStatus.AVAILABLE, f"Seat A2 was {s_a2.status}"
        assertions_passed += 2

        # 6. Verify hold record deleted
        hold_in_db = db.query(Hold).filter(Hold.id == hold.id).first()
        assert hold_in_db is None, "Expired hold record was not deleted!"
        assertions_passed += 1

        # 7. Verify HOLD_EXPIRED was recorded in the event's audit shard
        cleaner_shard_idx = audit_service.get_shard_index(event_id=cleaner_event.id)
        shard_logs, _ = audit_service.query_audit_logs(db, event_id=cleaner_event.id, action="HOLD_EXPIRED")
        assert len(shard_logs) >= 1
        assert "A1" in shard_logs[0]["details"]["released_seats"]
        assert "A2" in shard_logs[0]["details"]["released_seats"]
        assertions_passed += 2
        print(f"  [pass] Hold cleaner successfully reclaimed expired seats and logged HOLD_EXPIRED in shard {cleaner_shard_idx}.")

        # =====================================================================
        # PART 3: CHECK-IN BACKEND & QR TICKET CRYPTOGRAPHY
        # =====================================================================
        print("\n--- Part 3: Check-In Backend & QR Ticket Cryptography ---")

        # 1. Create a confirmed booking to test check-in
        hold_checkin = booking_service.hold_seats(db, student.id, cleaner_event.id, ["B1"])
        confirmed_booking = booking_service.confirm_hold(db, student.id, hold_checkin.id)
        assert confirmed_booking.status == BookingStatus.CONFIRMED
        assertions_passed += 1

        # 2. Generate signed QR ticket token
        ticket_token = checkin_service.generate_ticket_qr_token(confirmed_booking.id, cleaner_event.id)
        assert isinstance(ticket_token, str) and len(ticket_token) > 20
        assertions_passed += 1

        # 3. Decode and validate signed ticket token
        dec_bid, dec_eid = checkin_service.decode_ticket_qr_token(ticket_token)
        assert dec_bid == confirmed_booking.id
        assert dec_eid == cleaner_event.id
        assertions_passed += 2
        print(f"  [pass] Cryptographic QR ticket generation & validation verified.")

        # 4. Reject tampered token
        tampered_token = ticket_token[:-5] + "XXXXX"
        try:
            checkin_service.decode_ticket_qr_token(tampered_token)
            assert False, "Tampered token should have failed validation!"
        except HTTPException as exc:
            assert exc.status_code == 400
            assertions_passed += 1
        print(f"  [pass] Tampered QR ticket code successfully rejected (HTTP 400).")

        # 5. Check in booking via Organizer A (who owns cleaner_event)
        checkin_result = checkin_service.check_in_booking(
            db=db,
            booking_id=confirmed_booking.id,
            actor=org_a,
            event_id=cleaner_event.id,
        )
        assert checkin_result.booking_id == confirmed_booking.id
        assert "B1" in checkin_result.seat_numbers
        assert checkin_result.checked_in_at is not None
        assertions_passed += 3

        # Verify DB state
        db.refresh(confirmed_booking)
        assert confirmed_booking.checked_in_at is not None
        assert confirmed_booking.booking_seats[0].checked_in_at is not None
        assertions_passed += 2

        # Verify CHECKIN audit log
        checkin_logs, _ = audit_service.query_audit_logs(db, event_id=cleaner_event.id, action="CHECKIN")
        assert len(checkin_logs) >= 1
        assert checkin_logs[0]["details"]["booking_id"] == str(confirmed_booking.id)
        assertions_passed += 2
        print(f"  [pass] Valid gate check-in confirmed and audited in event shard.")

        # 6. Reject duplicate check-in (HTTP 409 Conflict)
        try:
            checkin_service.check_in_booking(
                db=db,
                booking_id=confirmed_booking.id,
                actor=org_a,
                event_id=cleaner_event.id,
            )
            assert False, "Duplicate check-in should have been rejected!"
        except HTTPException as exc:
            assert exc.status_code == 409
            assertions_passed += 1
        print(f"  [pass] Duplicate check-in correctly rejected with HTTP 409 Conflict.")

        # 7. Reject check-in on cancelled booking (HTTP 400 Bad Request)
        hold_cancel = booking_service.hold_seats(db, student.id, cleaner_event.id, ["C1"])
        booking_to_cancel = booking_service.confirm_hold(db, student.id, hold_cancel.id)
        booking_service.cancel_booking(db, student.id, booking_to_cancel.id)
        try:
            checkin_service.check_in_booking(
                db=db,
                booking_id=booking_to_cancel.id,
                actor=org_a,
            )
            assert False, "Cancelled booking should not be allowed to check in!"
        except HTTPException as exc:
            assert exc.status_code == 400
            assertions_passed += 1
        print(f"  [pass] Check-in on cancelled booking rejected with HTTP 400 Bad Request.")

        # =====================================================================
        # PART 4: ORGANIZER OPERATIONS & OWNERSHIP ENFORCEMENT
        # =====================================================================
        print("\n--- Part 4: Organizer Operations & Ownership Enforcement ---")

        # 1. Org A creates Event A, Org B creates Event B
        event_a_data = EventCreate(
            title=f"Org A Event {uuid.uuid4().hex[:6]}",
            location="Auditorium A",
            start_time=datetime.now(timezone.utc) + timedelta(days=5),
            booking_close_time=datetime.now(timezone.utc) + timedelta(days=4),
            total_seats=10,
        )
        event_a = event_service.create_event(db, event_a_data, creator=org_a)
        assert event_a.organizer_id == org_a.id
        assertions_passed += 1

        event_b_data = EventCreate(
            title=f"Org B Event {uuid.uuid4().hex[:6]}",
            location="Auditorium B",
            start_time=datetime.now(timezone.utc) + timedelta(days=6),
            booking_close_time=datetime.now(timezone.utc) + timedelta(days=5),
            total_seats=10,
        )
        event_b = event_service.create_event(db, event_b_data, creator=org_b)
        assert event_b.organizer_id == org_b.id
        assertions_passed += 1

        # 2. Org A can update Event A
        update_data = EventUpdate(
            title="Updated Title by Org A",
            description="New description",
            location="Auditorium A Updated",
            start_time=event_a.start_time,
            booking_close_time=event_a.booking_close_time,
            total_seats=10,
            version=event_a.version,
        )
        updated_a = event_service.update_event(db, event_a.id, update_data, actor=org_a)
        assert updated_a.title == "Updated Title by Org A"
        assert updated_a.version == 2
        assertions_passed += 2

        # 3. Org B CANNOT update Event A (HTTP 403 Forbidden)
        try:
            event_service.update_event(db, event_a.id, update_data, actor=org_b)
            assert False, "Org B should not be able to update Org A's event!"
        except HTTPException as exc:
            assert exc.status_code == 403
            assertions_passed += 1
        print(f"  [pass] Cross-organizer event modification rejected with HTTP 403 Forbidden.")

        # 4. Student books seat in Event A
        hold_a = booking_service.hold_seats(db, student.id, event_a.id, ["A1"])
        booking_a = booking_service.confirm_hold(db, student.id, hold_a.id)
        assertions_passed += 1

        # 5. Attendee manifest access
        # Org A can view manifest
        manifest_a = checkin_service.get_event_attendees(db, event_a.id, actor=org_a)
        assert manifest_a.total_bookings >= 1
        assert manifest_a.total_seats_reserved >= 1
        assertions_passed += 2

        # Org B CANNOT view Event A manifest (HTTP 403)
        try:
            checkin_service.get_event_attendees(db, event_a.id, actor=org_b)
            assert False, "Org B should not be able to view Org A's attendee manifest!"
        except HTTPException as exc:
            assert exc.status_code == 403
            assertions_passed += 1
        print(f"  [pass] Cross-organizer attendee manifest access rejected with HTTP 403 Forbidden.")

        # Org B CANNOT check in attendee for Event A (HTTP 403)
        try:
            checkin_service.check_in_booking(db, booking_a.id, actor=org_b)
            assert False, "Org B should not be able to check in attendees for Org A's event!"
        except HTTPException as exc:
            assert exc.status_code == 403
            assertions_passed += 1
        print(f"  [pass] Cross-organizer venue check-in rejected with HTTP 403 Forbidden.")

        # Admin CAN view manifest and check in (bypasses ownership)
        admin_manifest = checkin_service.get_event_attendees(db, event_a.id, actor=admin)
        assert admin_manifest.total_bookings >= 1
        admin_checkin = checkin_service.check_in_booking(db, booking_a.id, actor=admin)
        assert admin_checkin.checked_in_at is not None
        assertions_passed += 2
        print(f"  [pass] Admin successfully accessed attendee manifest and completed check-in.")

        # 6. Verify list_organizer_events filters correctly
        org_a_events = event_service.list_organizer_events(db, org_a.id, is_admin=False)
        org_a_ids = {e.id for e in org_a_events}
        assert event_a.id in org_a_ids
        assert event_b.id not in org_a_ids
        assertions_passed += 2
        print(f"  [pass] list_organizer_events strictly isolated to organizer's events.")

        # =====================================================================
        # PART 5: LIVE FASTAPI API ENDPOINTS VERIFICATION
        # =====================================================================
        print("\n--- Part 5: Live API Endpoints (HTTP TestClient) ---")

        # 1. Login endpoints and audit trail
        # Successful login
        login_res = client.post("/auth/login", json={"username": "student_user", "password": "StudentPass123!"})
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        assert settings.AUTH_COOKIE_NAME in login_res.cookies
        assertions_passed += 2

        # Failed login
        fail_res = client.post("/auth/login", json={"username": "student_user", "password": "WrongPassword!"})
        assert fail_res.status_code == 401
        assertions_passed += 1

        # 2. Login as Admin to inspect audit logs
        admin_login = client.post("/auth/login", json={"username": "admin_user", "password": "AdminPass123!"})
        assert admin_login.status_code == 200
        admin_cookies = admin_login.cookies
        assertions_passed += 1

        # Query all audit logs via API
        audit_res = client.get("/audit-logs?limit=5", cookies=admin_cookies)
        assert audit_res.status_code == 200
        audit_data = audit_res.json()
        assert "entries" in audit_data
        assert audit_data["total"] >= 1
        assertions_passed += 2
        print(f"  [pass] GET /audit-logs returned {audit_data['total']} entries to Admin.")

        # 3. Login as Org A and view attendees
        org_a_login = client.post("/auth/login", json={"username": "organizer_alpha", "password": "TestPass123!"})
        assert org_a_login.status_code == 200
        org_a_cookies = org_a_login.cookies
        assertions_passed += 1

        attendees_res = client.get(f"/events/{event_a.id}/attendees", cookies=org_a_cookies)
        assert attendees_res.status_code == 200
        att_data = attendees_res.json()
        assert att_data["event_id"] == str(event_a.id)
        assert len(att_data["attendees"]) >= 1
        assertions_passed += 2
        print(f"  [pass] GET /events/{{event_a.id}}/attendees succeeded for owner Organizer A.")

        # 4. Org B attempting to view Event A attendees via API (HTTP 403)
        org_b_login = client.post("/auth/login", json={"username": "organizer_beta", "password": "TestPass123!"})
        assert org_b_login.status_code == 200
        org_b_cookies = org_b_login.cookies
        assertions_passed += 1

        unauth_attendees = client.get(f"/events/{event_a.id}/attendees", cookies=org_b_cookies)
        assert unauth_attendees.status_code == 403
        assertions_passed += 1
        print(f"  [pass] GET /events/{{event_a.id}}/attendees denied for non-owner Organizer B (HTTP 403).")

        # 5. Student booking and ticket token via API
        student_cookies = login_res.cookies
        hold_res = client.post(
            f"/events/{event_a.id}/hold",
            json={"seat_numbers": ["A2"]},
            cookies=student_cookies,
        )
        assert hold_res.status_code == 201
        hold_id = hold_res.json()["id"]
        assertions_passed += 1

        confirm_res = client.post(f"/holds/{hold_id}/confirm", cookies=student_cookies)
        assert confirm_res.status_code == 201
        new_booking_id = confirm_res.json()["id"]
        assertions_passed += 1

        # Get QR ticket
        ticket_res = client.get(f"/bookings/{new_booking_id}/ticket", cookies=student_cookies)
        assert ticket_res.status_code == 200
        qr_token = ticket_res.json()["ticket_token"]
        assert len(qr_token) > 20
        assertions_passed += 2
        print(f"  [pass] GET /bookings/{{id}}/ticket returned valid signed QR code.")

        # Gate check-in via QR token endpoint
        gate_checkin = client.post(
            f"/events/{event_a.id}/check-in",
            json={"qr_token": qr_token},
            cookies=org_a_cookies,
        )
        assert gate_checkin.status_code == 200
        assert gate_checkin.json()["booking_id"] == new_booking_id
        assertions_passed += 2
        print(f"  [pass] POST /events/{{id}}/check-in processed gate entry via QR code.")

        # Duplicate check-in via QR token endpoint
        dup_gate = client.post(
            f"/events/{event_a.id}/check-in",
            json={"qr_token": qr_token},
            cookies=org_a_cookies,
        )
        assert dup_gate.status_code == 409
        assertions_passed += 1
        print(f"  [pass] Duplicate gate check-in via QR rejected with HTTP 409.")

        print("\n" + "=" * 70)
        print(f"SUCCESS: ALL {assertions_passed}/{assertions_passed} OPERATIONS ASSERTIONS PASSED!")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    run_tests()
