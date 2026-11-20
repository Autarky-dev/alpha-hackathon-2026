"""
backend/scripts/test_auth.py
----------------------------
Comprehensive automated verification suite for SeatLock Authentication & RBAC.

Tests:
  1. Unauthenticated access rejection (HTTP 401)
  2. Invalid credentials rejection (HTTP 401)
  3. Successful login & HttpOnly cookie issuance (HTTP 200)
  4. Student role permissions & restrictions (HTTP 200 & 403)
  5. Organizer & Admin role permissions & restrictions (HTTP 200 & 403)
  6. Logout & session invalidation (HTTP 200 & 401)
"""

import os
import sys

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def run_tests():
    print("=" * 65)
    print("  SeatLock — Authentication & RBAC Verification Suite")
    print("=" * 65)

    client = TestClient(app)
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
    # TEST 1: Unauthenticated Access Rejection
    # -----------------------------------------------------------------------
    print("\n--- [Test 1] Unauthenticated Access Rejection (HTTP 401) ---")
    endpoints_to_test = [
        "/auth/me",
        "/auth/test/authenticated",
        "/auth/test/student",
        "/auth/test/organizer",
        "/auth/test/admin",
    ]
    for ep in endpoints_to_test:
        resp = client.get(ep)
        record_check(
            f"GET {ep} without cookie returns 401",
            resp.status_code == 401,
            f"Got {resp.status_code}: {resp.text}",
        )

    # -----------------------------------------------------------------------
    # TEST 2: Invalid Credentials Rejection
    # -----------------------------------------------------------------------
    print("\n--- [Test 2] Invalid Credentials Rejection (HTTP 401) ---")
    # Wrong password for existing user
    resp = client.post(
        "/auth/login",
        json={"username": settings.SEED_STUDENT_USERNAME, "password": "WrongPassword999!"},
    )
    record_check(
        "Login with incorrect password returns 401",
        resp.status_code == 401 and "Invalid" in resp.json().get("detail", ""),
        f"Got {resp.status_code}: {resp.text}",
    )
    record_check(
        "Login with incorrect password does not set auth cookie",
        settings.AUTH_COOKIE_NAME not in resp.cookies,
    )

    # Nonexistent user
    resp = client.post(
        "/auth/login",
        json={"username": "nonexistent_ghost_user_xyz", "password": "AnyPassword123!"},
    )
    record_check(
        "Login with nonexistent username returns 401",
        resp.status_code == 401 and "Invalid" in resp.json().get("detail", ""),
        f"Got {resp.status_code}: {resp.text}",
    )

    # -----------------------------------------------------------------------
    # TEST 3: Successful Login & Cookie Verification
    # -----------------------------------------------------------------------
    print("\n--- [Test 3] Successful Login & HttpOnly Cookie Issuance (HTTP 200) ---")
    resp = client.post(
        "/auth/login",
        json={
            "username": settings.SEED_STUDENT_USERNAME,
            "password": settings.SEED_STUDENT_PASSWORD,
        },
    )
    data = resp.json()
    record_check(
        "Student login returns HTTP 200",
        resp.status_code == 200,
        f"Got {resp.status_code}: {resp.text}",
    )
    record_check(
        "Login response contains username and student role",
        data.get("user", {}).get("username") == settings.SEED_STUDENT_USERNAME
        and data.get("user", {}).get("role") == "student",
    )
    record_check(
        "Login response does NOT expose password_hash",
        "password_hash" not in data.get("user", {}) and "password" not in data.get("user", {}),
    )
    record_check(
        f"Response sets {settings.AUTH_COOKIE_NAME} cookie",
        settings.AUTH_COOKIE_NAME in resp.cookies,
    )

    # Verify cookie attributes from Set-Cookie header
    set_cookie_header = resp.headers.get("set-cookie", "")
    record_check(
        "Auth cookie has HttpOnly flag set",
        "httponly" in set_cookie_header.lower(),
        f"Set-Cookie: {set_cookie_header}",
    )
    record_check(
        f"Auth cookie has SameSite={settings.AUTH_COOKIE_SAMESITE} flag set",
        f"samesite={settings.AUTH_COOKIE_SAMESITE.lower()}" in set_cookie_header.lower(),
        f"Set-Cookie: {set_cookie_header}",
    )

    # -----------------------------------------------------------------------
    # TEST 4: Student Role Access & Restrictions
    # -----------------------------------------------------------------------
    print("\n--- [Test 4] Student Role Access & Restrictions ---")
    # client currently holds student cookie from Test 3
    resp = client.get("/auth/me")
    record_check(
        "Student can access GET /auth/me",
        resp.status_code == 200 and resp.json().get("role") == "student",
    )

    resp = client.get("/auth/test/authenticated")
    record_check(
        "Student can access GET /auth/test/authenticated",
        resp.status_code == 200,
    )

    resp = client.get("/auth/test/student")
    record_check(
        "Student can access GET /auth/test/student (HTTP 200)",
        resp.status_code == 200,
    )

    resp = client.get("/auth/test/organizer")
    record_check(
        "Student is REJECTED from GET /auth/test/organizer (HTTP 403 Forbidden)",
        resp.status_code == 403,
        f"Got {resp.status_code}: {resp.text}",
    )

    resp = client.get("/auth/test/admin")
    record_check(
        "Student is REJECTED from GET /auth/test/admin (HTTP 403 Forbidden)",
        resp.status_code == 403,
        f"Got {resp.status_code}: {resp.text}",
    )

    # -----------------------------------------------------------------------
    # TEST 5: Organizer & Admin Role Restrictions
    # -----------------------------------------------------------------------
    print("\n--- [Test 5] Organizer & Admin Role Restrictions ---")
    # Fresh client for Organizer
    org_client = TestClient(app)
    resp = org_client.post(
        "/auth/login",
        json={
            "username": settings.SEED_ORGANIZER_USERNAME,
            "password": settings.SEED_ORGANIZER_PASSWORD,
        },
    )
    record_check("Organizer login returns HTTP 200", resp.status_code == 200)

    resp = org_client.get("/auth/test/organizer")
    record_check(
        "Organizer can access GET /auth/test/organizer (HTTP 200)",
        resp.status_code == 200,
    )

    resp = org_client.get("/auth/test/admin")
    record_check(
        "Organizer is REJECTED from GET /auth/test/admin (HTTP 403 Forbidden)",
        resp.status_code == 403,
    )

    resp = org_client.get("/auth/test/student")
    record_check(
        "Organizer is REJECTED from GET /auth/test/student (HTTP 403 Forbidden)",
        resp.status_code == 403,
    )

    # Fresh client for Admin
    admin_client = TestClient(app)
    resp = admin_client.post(
        "/auth/login",
        json={
            "username": settings.SEED_ADMIN_USERNAME,
            "password": settings.SEED_ADMIN_PASSWORD,
        },
    )
    record_check("Admin login returns HTTP 200", resp.status_code == 200)

    resp = admin_client.get("/auth/test/admin")
    record_check(
        "Admin can access GET /auth/test/admin (HTTP 200)",
        resp.status_code == 200,
    )

    resp = admin_client.get("/auth/test/organizer")
    record_check(
        "Admin can access GET /auth/test/organizer (HTTP 200, elevated)",
        resp.status_code == 200,
    )

    resp = admin_client.get("/auth/test/student")
    record_check(
        "Admin is REJECTED from GET /auth/test/student (HTTP 403, strictly student)",
        resp.status_code == 403,
    )

    # -----------------------------------------------------------------------
    # TEST 6: Logout & Session Invalidation
    # -----------------------------------------------------------------------
    print("\n--- [Test 6] Logout & Session Invalidation ---")
    # Verify admin_client is currently authenticated
    resp = admin_client.get("/auth/me")
    record_check("Pre-logout: session is valid (HTTP 200)", resp.status_code == 200)

    # Call logout
    resp = admin_client.post("/auth/logout")
    record_check("POST /auth/logout returns HTTP 200", resp.status_code == 200)

    # Check Set-Cookie clears or expires cookie
    set_cookie_header = resp.headers.get("set-cookie", "")
    record_check(
        "Logout response includes Set-Cookie clearing the cookie",
        settings.AUTH_COOKIE_NAME in set_cookie_header
        and ('max-age=0' in set_cookie_header.lower() or 'expires=thu, 01 jan 1970' in set_cookie_header.lower() or '""' in set_cookie_header),
        f"Set-Cookie: {set_cookie_header}",
    )

    # Subsequent request using the cleared client must return 401
    resp = admin_client.get("/auth/me")
    record_check(
        "Post-logout: GET /auth/me returns 401 Unauthorized",
        resp.status_code == 401,
        f"Got {resp.status_code}: {resp.text}",
    )

    resp = admin_client.get("/auth/test/admin")
    record_check(
        "Post-logout: GET /auth/test/admin returns 401 Unauthorized",
        resp.status_code == 401,
        f"Got {resp.status_code}: {resp.text}",
    )

    # -----------------------------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------------------------
    print("\n" + "=" * 65)
    print(f"  Verification Result: {passed_checks}/{total_checks} checks PASSED")
    print("=" * 65)

    return passed_checks == total_checks


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
