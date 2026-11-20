"""
backend/scripts/init_db.py
---------------------------
Database initialisation script.

What it does
------------
1. Imports every model so SQLAlchemy's Base.metadata knows about all tables.
2. Calls Base.metadata.create_all(engine) — PostgreSQL equivalent of running
   all the CREATE TABLE / CREATE TYPE / CREATE INDEX statements.
3. Verifies the tables were actually created by querying the PostgreSQL
   information_schema.

What it does NOT do
-------------------
- Does not drop existing tables (safe to run on a database that already has data).
- Does not insert any seed data.
- Does not start the FastAPI server.
- Does not expose or print any credentials.

Run from the backend/ directory:
    ../.venv/Scripts/python scripts/init_db.py
"""

import sys
import os

# Allow Python to find the app package (backend/app/...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

# --- Import engine and Base from the verified foundation ---
from app.core.database import engine, Base

# --- Import ALL models so Base.metadata registers their tables ---
# This is the critical step: if a model is not imported, its table
# will not be created even if the class exists.
import app.models  # noqa: F401 — side-effect import registers all models


# The tables we expect to find after create_all().
EXPECTED_TABLES = [
    "users",
    "events",
    "seats",
    "holds",
    "hold_seats",
    "bookings",
    "booking_seats",
    "audit_logs_0",
    "audit_logs_1",
    "audit_logs_2",
    "audit_logs_3",
]


def ensure_enum_values() -> None:
    """
    Ensure newer enum values (student, organizer) exist if the user_role type
    was previously created in PostgreSQL without them.
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        res = conn.execute(text("SELECT 1 FROM pg_type WHERE typname = 'user_role'")).scalar()
        if res:
            conn.execute(text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'student'"))
            conn.execute(text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'organizer'"))
        # Safe non-destructive column additions (only if tables exist)
        res_events = conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'events'")).scalar()
        if res_events:
            conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS organizer_id UUID REFERENCES users(id) ON DELETE SET NULL"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_events_organizer_id ON events (organizer_id)"))

        res_bookings = conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'bookings'")).scalar()
        if res_bookings:
            conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS checked_in_at TIMESTAMP WITH TIME ZONE DEFAULT NULL"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bookings_checked_in_at ON bookings (checked_in_at)"))

        res_bseats = conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'booking_seats'")).scalar()
        if res_bseats:
            conn.execute(text("ALTER TABLE booking_seats ADD COLUMN IF NOT EXISTS checked_in_at TIMESTAMP WITH TIME ZONE DEFAULT NULL"))


def create_tables() -> None:
    """
    Issue CREATE TABLE ... IF NOT EXISTS for every model registered on Base.
    checkfirst=True means: skip tables that already exist instead of erroring.
    """
    ensure_enum_values()
    print("\n[init_db] Creating tables (skipping any that already exist)...")
    Base.metadata.create_all(bind=engine, checkfirst=True)
    print("[init_db] create_all() completed without error.")


def verify_tables() -> bool:
    """
    Query PostgreSQL's information_schema to confirm every expected table
    was actually created. Returns True if all tables are present.
    """
    print("\n[init_db] Verifying tables in PostgreSQL information_schema...")

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
        )
        # Collect the names of tables that actually exist.
        existing = {row.table_name for row in result}

    all_ok = True
    for table in sorted(EXPECTED_TABLES):
        if table in existing:
            print(f"  ✓  {table}")
        else:
            print(f"  ✗  {table}  ← MISSING")
            all_ok = False

    return all_ok


def verify_enum_types() -> None:
    """
    Confirm the PostgreSQL ENUM types were created.
    These are created automatically by SQLAlchemy alongside the tables.
    """
    print("\n[init_db] Verifying PostgreSQL ENUM types...")

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT typname
                FROM pg_type
                WHERE typtype = 'e'
                ORDER BY typname
            """)
        )
        enum_types = [row.typname for row in result]

    expected_enums = ["booking_status", "seat_status", "user_role"]
    for name in expected_enums:
        if name in enum_types:
            print(f"  ✓  {name}")
        else:
            print(f"  ✗  {name}  ← MISSING")


def verify_indexes() -> None:
    """
    Spot-check that key indexes were created.
    """
    print("\n[init_db] Verifying key indexes...")

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY indexname
            """)
        )
        existing_indexes = {row.indexname for row in result}

    key_indexes = [
        "uq_users_username",
        "uq_seats_event_seat_number",
        "ix_seats_event_id_status",
        "ix_holds_expires_at",
        "ix_holds_user_event",
        "ix_bookings_user_id",
        "ix_bookings_event_id",
        "ix_audit_logs_0_event_id",
        "ix_audit_logs_1_event_id",
        "ix_audit_logs_2_event_id",
        "ix_audit_logs_3_event_id",
    ]

    for idx in key_indexes:
        status = "✓" if idx in existing_indexes else "✗  ← MISSING"
        print(f"  {status}  {idx}")


def main() -> None:
    print("=" * 55)
    print("  SeatLock — Database Initialisation")
    print("=" * 55)

    try:
        create_tables()
        tables_ok = verify_tables()
        verify_enum_types()
        verify_indexes()

        print()
        if tables_ok:
            print("=" * 55)
            print("  ✓ Schema initialisation complete.")
            print("=" * 55)
            sys.exit(0)
        else:
            print("=" * 55)
            print("  ✗ One or more tables are missing. Check errors above.")
            print("=" * 55)
            sys.exit(1)

    except SQLAlchemyError as exc:
        # Print the error type but NOT any connection URL or credentials.
        print(f"\n  ✗ Database error: {type(exc).__name__}")
        print(f"    {exc.args[0][:300] if exc.args else '(no message)'}")
        sys.exit(1)


if __name__ == "__main__":
    main()
