"""
SeatLock — End-to-End Integration & Verification Test Suite
===========================================================
Validates the complete application lifecycle across:
- Authentication & HttpOnly cookie sessions (/auth/login, /auth/me, /auth/logout)
- Role-based authorization (student, organizer, admin)
- Event inventory & live seat availability (/events, /events/{id}/seats)
- Seat holding with 5-minute timeout (/events/{id}/hold)
- Hold confirmation into booking (/holds/{id}/confirm)
- Ticket retrieval with signed QR token (/bookings/{id}/ticket)
- Gate check-in with QR token & duplicate prevention (/events/{id}/check-in)
- Event creation and Optimistic Concurrency Control (/events, PUT /events/{id})
- Booking cancellation and seat release (/bookings/{id}/cancel)
- Federated 4-shard audit logging (/audit-logs across audit_logs_0..3)
- Frontend preview server template rendering & static assets
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure backend and frontend are importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "frontend"))

from starlette.testclient import TestClient
from app.main import app as backend_app
import preview as frontend_module
frontend_app = frontend_module.app

# Client wrappers
backend_client = TestClient(backend_app, base_url="http://127.0.0.1:8000")
frontend_client = TestClient(frontend_app, base_url="http://127.0.0.1:3000")

PASS = "[PASS]"
FAIL = "[FAIL]"
checks_passed = 0
checks_total = 0

def check(condition: bool, description: str):
    global checks_passed, checks_total
    checks_total += 1
    if condition:
        checks_passed += 1
        print(f"  {PASS} {description}")
    else:
        print(f"  {FAIL} {description}")
        raise AssertionError(f"Check failed: {description}")


def test_e2e():
    print("\n=======================================================")
    print(" SEATLOCK — END-TO-END INTEGRATION TEST SUITE")
    print("=======================================================\n")

    # -----------------------------------------------------------------
    # PHASE 1: Health & Public Endpoints
    # -----------------------------------------------------------------
    print("Phase 1: Backend Health & Public Endpoints")
    res = backend_client.get("/health")
    check(res.status_code == 200, "GET /health returns 200 OK")
    check(res.json().get("status") in ("ok", "healthy"), "Health status is 'ok'/'healthy'")

    res = backend_client.get("/events")
    check(res.status_code == 200, "GET /events returns 200 OK")
    events = res.json()
    check(isinstance(events, list) and len(events) >= 1, "Public events catalog lists active events")

    # -----------------------------------------------------------------
    # PHASE 2: Authentication & Session Recognition
    # -----------------------------------------------------------------
    print("\nPhase 2: Authentication & RBAC Session Management")
    # 2.1 Student session
    student_c = TestClient(backend_app, base_url="http://127.0.0.1:8000")
    login_res = student_c.post("/auth/login", json={"username": "student_user", "password": "StudentPass123!"})
    check(login_res.status_code == 200, "Student login returns 200 OK")
    check("seatlock_access_token" in login_res.cookies, "HttpOnly cookie 'seatlock_access_token' set")

    me_res = student_c.get("/auth/me")
    check(me_res.status_code == 200, "GET /auth/me returns 200 OK for student")
    check(me_res.json().get("username") == "student_user", "Current user is 'student_user'")
    check(me_res.json().get("role") == "student", "Current user role is 'student'")

    # 2.2 Organizer session
    organizer_c = TestClient(backend_app, base_url="http://127.0.0.1:8000")
    org_login = organizer_c.post("/auth/login", json={"username": "organizer_user", "password": "OrganizerPass123!"})
    check(org_login.status_code == 200, "Organizer login returns 200 OK")
    me_org = organizer_c.get("/auth/me")
    check(me_org.json().get("role") == "organizer", "Organizer role recognized from cookie")

    # 2.3 Admin session
    admin_c = TestClient(backend_app, base_url="http://127.0.0.1:8000")
    adm_login = admin_c.post("/auth/login", json={"username": "admin_user", "password": "AdminPass123!"})
    check(adm_login.status_code == 200, "Admin login returns 200 OK")
    me_adm = admin_c.get("/auth/me")
    check(me_adm.json().get("role") == "admin", "Admin role recognized from cookie")

    # 2.4 Logout verification
    temp_c = TestClient(backend_app, base_url="http://127.0.0.1:8000")
    temp_c.post("/auth/login", json={"username": "student_user", "password": "StudentPass123!"})
    logout_res = temp_c.post("/auth/logout")
    check(logout_res.status_code == 200, "POST /auth/logout returns 200 OK")
    unauth_me = temp_c.get("/auth/me")
    check(unauth_me.status_code == 401, "GET /auth/me returns 401 Unauthorized after logout")

    # -----------------------------------------------------------------
    # PHASE 3: Dedicated Organizer Event & Core Seat Reservation
    # -----------------------------------------------------------------
    print("\nPhase 3: Organizer Event Creation & Seat Reservation Lifecycle")
    now_utc = datetime.now(timezone.utc)
    evt_start = (now_utc + timedelta(days=14)).isoformat()
    evt_close = (now_utc + timedelta(days=13)).isoformat()

    # Organizer creates a fresh test event to ensure 100% ownership
    org_evt_res = organizer_c.post("/events", json={
        "title": "Alpha Live Integration Concert",
        "location": "Grand Arena Hall 1",
        "start_time": evt_start,
        "booking_close_time": evt_close,
        "total_seats": 20,
        "description": "Integration test event for end-to-end verification"
    })
    check(org_evt_res.status_code == 201, "Organizer creates event: 201 Created")
    live_event = org_evt_res.json()
    live_event_id = live_event["id"]
    check(live_event["total_seats"] == 20, "Event initialized with 20 seats")
    check(live_event["version"] == 1, "Event initial version is 1")
    print(f"  -> Created active organizer event: '{live_event['title']}' ({live_event_id})")

    # Check live seat map
    seat_map_res = backend_client.get(f"/events/{live_event_id}/seats")
    check(seat_map_res.status_code == 200, "GET /events/{id}/seats returns 200 OK")
    seat_payload = seat_map_res.json()
    seats = seat_payload["seats"]
    check(len(seats) == 20, "Venue seat map has 20 seats")
    check(seat_payload["available_count"] == 20, "All 20 seats initially available")

    # Pick 2 seats for student hold
    target_seats = ["A1", "A2"]
    print(f"  -> Student holds seats: {target_seats}")

    hold_res = student_c.post(f"/events/{live_event_id}/hold", json={"seat_numbers": target_seats})
    check(hold_res.status_code == 201, "POST /events/{id}/hold returns 201 Created")
    hold_data = hold_res.json()
    hold_id = hold_data["id"]
    check(set(hold_data["seat_numbers"]) == set(target_seats), "Hold payload matches requested seats")
    check("expires_at" in hold_data, "Hold includes 5-min expires_at timestamp")

    # Verify seats are held
    res_seats_held = student_c.get(f"/events/{live_event_id}/seats")
    held_map = {s["seat_number"]: s["status"] for s in res_seats_held.json()["seats"]}
    for s_num in target_seats:
        check(held_map.get(s_num) == "held", f"Seat {s_num} status changed to 'held'")

    # Confirm hold into permanent booking
    confirm_res = student_c.post(f"/holds/{hold_id}/confirm")
    check(confirm_res.status_code == 201, "POST /holds/{id}/confirm returns 201 Created")
    booking_data = confirm_res.json()
    booking_id = booking_data["id"]
    check(booking_data["status"].lower() == "confirmed", "Booking status is 'confirmed'")
    check(set(booking_data["seat_numbers"]) == set(target_seats), "Booking seats match confirmed hold")
    print(f"  -> Confirmed booking ID: {booking_id}")

    # Verify seats are now booked
    res_seats_booked = student_c.get(f"/events/{live_event_id}/seats")
    booked_map = {s["seat_number"]: s["status"] for s in res_seats_booked.json()["seats"]}
    for s_num in target_seats:
        check(booked_map.get(s_num) == "booked", f"Seat {s_num} status changed to 'booked'")

    # -----------------------------------------------------------------
    # PHASE 4: Student Bookings & QR Ticket Generation
    # -----------------------------------------------------------------
    print("\nPhase 4: My Bookings & QR Ticket Generation")
    my_bookings_res = student_c.get("/bookings/me")
    check(my_bookings_res.status_code == 200, "GET /bookings/me returns 200 OK")
    my_bookings = my_bookings_res.json()
    check(any(b["id"] == booking_id for b in my_bookings), "New booking is present in student's bookings list")

    ticket_res = student_c.get(f"/bookings/{booking_id}/ticket")
    check(ticket_res.status_code == 200, "GET /bookings/{id}/ticket returns 200 OK")
    ticket_data = ticket_res.json()
    qr_token = ticket_data.get("ticket_token")
    check(bool(qr_token and len(qr_token) > 20), "Signed QR ticket token received")
    check(ticket_data.get("booking_id") == booking_id, "Ticket token response has booking_id")

    # -----------------------------------------------------------------
    # PHASE 5: Organizer Dashboard, Attendee Manifest & Gate Check-In
    # -----------------------------------------------------------------
    print("\nPhase 5: Organizer Dashboard & Gate Check-In")
    # List organizer's events
    org_events_res = organizer_c.get("/events/organizer/mine")
    check(org_events_res.status_code == 200, "GET /events/organizer/mine returns 200 OK")
    org_events = org_events_res.json()
    check(any(e["id"] == live_event_id for e in org_events), "Created event appears in organizer's event list")

    # Fetch attendee manifest
    attendees_res = organizer_c.get(f"/events/{live_event_id}/attendees")
    check(attendees_res.status_code == 200, "GET /events/{id}/attendees returns 200 OK")
    manifest = attendees_res.json()
    attendees = manifest.get("attendees", [])
    matching_attendee = next((a for a in attendees if a["booking_id"] == booking_id), None)
    check(matching_attendee is not None, "Confirmed booking appears in organizer attendee manifest")
    check(matching_attendee["status"].lower() == "confirmed", "Attendee status is initially 'confirmed'")

    # Gate Check-In via QR Token
    checkin_res = organizer_c.post(f"/events/{live_event_id}/check-in", json={"qr_token": qr_token})
    check(checkin_res.status_code == 200, "POST /events/{id}/check-in via QR token returns 200 OK")
    checkin_data = checkin_res.json()
    check(checkin_data["checked_in_at"] is not None, "Gate check-in recorded timestamp")
    check(checkin_data["booking_id"] == booking_id, "Check-in returned target booking_id")

    # Duplicate check-in protection
    dup_res = organizer_c.post(f"/events/{live_event_id}/check-in", json={"qr_token": qr_token})
    check(dup_res.status_code == 409, "Duplicate gate check-in correctly rejected with 409 Conflict")

    # Verify manifest reflects checked-in status
    attendees_res2 = organizer_c.get(f"/events/{live_event_id}/attendees")
    updated_att = next(a for a in attendees_res2.json().get("attendees", []) if a["booking_id"] == booking_id)
    check(updated_att["checked_in_at"] is not None, "Manifest records checked_in_at timestamp")

    # -----------------------------------------------------------------
    # PHASE 6: Event Management & Optimistic Concurrency Control (OCC)
    # -----------------------------------------------------------------
    print("\nPhase 6: Event Management & Optimistic Concurrency Control (OCC)")
    # Successful update with matching version=1
    update_res = organizer_c.put(f"/events/{live_event_id}", json={
        "title": "Alpha Live Integration Concert (Updated Venue)",
        "location": "Grand Arena Hall 2",
        "start_time": evt_start,
        "booking_close_time": evt_close,
        "total_seats": 20,
        "version": 1
    })
    check(update_res.status_code == 200, "PUT /events/{id} with version=1 returns 200 OK")
    check(update_res.json()["version"] == 2, "Event version successfully bumped to 2")

    # Conflicting update with stale version=1
    stale_update = organizer_c.put(f"/events/{live_event_id}", json={
        "title": "Stale Concurrent Update",
        "location": "Grand Arena Hall 2",
        "start_time": evt_start,
        "booking_close_time": evt_close,
        "total_seats": 20,
        "version": 1  # Stale! Current version is 2
    })
    check(stale_update.status_code == 409, "Stale version update correctly rejected with 409 Conflict")

    # -----------------------------------------------------------------
    # PHASE 7: Booking Cancellation & Seat Release
    # -----------------------------------------------------------------
    print("\nPhase 7: Booking Cancellation & Inventory Release")
    # Hold and book another seat to test cancellation
    avail_seats2 = [s["seat_number"] for s in student_c.get(f"/events/{live_event_id}/seats").json()["seats"] if s["status"] == "available"]
    check(len(avail_seats2) >= 1, "Event has available seats for cancellation test")
    cancel_seat = avail_seats2[0]

    h2 = student_c.post(f"/events/{live_event_id}/hold", json={"seat_numbers": [cancel_seat]}).json()
    b2 = student_c.post(f"/holds/{h2['id']}/confirm").json()
    check(b2["status"].lower() == "confirmed", "Confirmed booking to be cancelled")

    # Cancel booking
    cancel_res = student_c.post(f"/bookings/{b2['id']}/cancel")
    check(cancel_res.status_code == 200, "POST /bookings/{id}/cancel returns 200 OK")
    check(cancel_res.json()["status"].lower() == "cancelled", "Booking status changed to 'cancelled'")

    # Verify seat is back to available
    seats_after_cancel = {s["seat_number"]: s["status"] for s in student_c.get(f"/events/{live_event_id}/seats").json()["seats"]}
    check(seats_after_cancel.get(cancel_seat) == "available", f"Seat {cancel_seat} successfully returned to 'available'")

    # -----------------------------------------------------------------
    # PHASE 8: 4-Shard Federated Audit Logging
    # -----------------------------------------------------------------
    print("\nPhase 8: 4-Shard Federated Audit Logging (audit_logs_0..3)")
    audit_res = admin_c.get("/audit-logs?limit=50")
    check(audit_res.status_code == 200, "GET /audit-logs returns 200 OK for Admin")
    audit_data = audit_res.json()
    check(audit_data["total"] > 0, f"Federated query returned {audit_data['total']} total audit entries")
    entries = audit_data["entries"]
    check(len(entries) > 0, "Audit entries list is non-empty")

    shards_observed = set(e["shard_id"] for e in entries)
    check(all(s in (0, 1, 2, 3) for s in shards_observed), f"Shard IDs belong to 0..3: {shards_observed}")

    # Action filter test
    checkin_logs = admin_c.get("/audit-logs?action=CHECKIN").json()
    check(all(e["action"] == "CHECKIN" for e in checkin_logs["entries"]), "Filter by action='CHECKIN' returns only CHECKIN logs")

    hold_logs = admin_c.get("/audit-logs?action=SEAT_HOLD").json()
    check(all(e["action"] == "SEAT_HOLD" for e in hold_logs["entries"]), "Filter by action='SEAT_HOLD' returns only SEAT_HOLD logs")

    # -----------------------------------------------------------------
    # PHASE 9: Frontend Preview Server & Jinja2 Templates
    # -----------------------------------------------------------------
    print("\nPhase 9: Frontend Preview Server & Jinja2 Templates (Port 3000)")
    for route in ["/", "/login", "/events", f"/events/{live_event_id}/seats", "/bookings", "/organizer", "/admin"]:
        page_res = frontend_client.get(route)
        check(page_res.status_code == 200, f"Frontend route '{route}' renders 200 OK")
        check("SeatLock" in page_res.text, f"Frontend route '{route}' contains 'SeatLock' title")

    # Static assets
    for asset in ["/static/js/api.js", "/static/js/seat_map.js", "/static/js/organizer.js", "/static/js/admin.js", "/static/js/bookings.js", "/static/js/events.js", "/static/js/qrcode.min.js"]:
        asset_res = frontend_client.get(asset)
        check(asset_res.status_code == 200, f"Static asset '{asset}' serves 200 OK")

    print("\n=======================================================")
    print(f" ALL CHECKS PASSED: {checks_passed} / {checks_total}")
    print(" SEATLOCK FRONTEND-BACKEND INTEGRATION FULLY VERIFIED!")
    print("=======================================================\n")


if __name__ == "__main__":
    test_e2e()
