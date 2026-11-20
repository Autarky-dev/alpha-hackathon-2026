"""
backend/app/core/db_init.py
---------------------------
Controlled, idempotent, and concurrency-safe database initialization for SeatLock.

Key Features:
  - Free-tier Render friendly: runs within application lifespan startup.
  - Concurrency-safe: utilizes a PostgreSQL advisory lock (ADVISORY_LOCK_ID) so
    multiple workers or instances do not run concurrent migrations/seeding.
  - Idempotent: checks for existing tables, enum types, seed users, and demo events
    before executing any DDL or inserts.
  - Performance: skips expensive bcrypt hashing and redundant queries if seed
    users and demo events already exist (< 5ms check).
  - Safe: NEVER drops, resets, or deletes existing database data.
"""

import sys
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
import app.models  # Registers all models with Base.metadata

ADVISORY_LOCK_ID = 84729104  # Unique 64-bit integer for SeatLock database initialization


def _ensure_enum_values_and_columns(conn) -> None:
    """Ensure newer enum values and columns exist if types/tables were previously created."""
    # Note: conn must be in autocommit mode for ALTER TYPE ... ADD VALUE
    res_type = conn.execute(text("SELECT 1 FROM pg_type WHERE typname = 'user_role'")).scalar()
    if res_type:
        conn.execute(text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'student'"))
        conn.execute(text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'organizer'"))

    # Check if events table exists before adding columns
    res_events = conn.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'events'")
    ).scalar()
    if res_events:
        conn.execute(
            text(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS organizer_id UUID REFERENCES users(id) ON DELETE SET NULL"
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_events_organizer_id ON events (organizer_id)"))

    # Check if bookings table exists before adding columns
    res_bookings = conn.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'bookings'")
    ).scalar()
    if res_bookings:
        conn.execute(
            text(
                "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS checked_in_at TIMESTAMP WITH TIME ZONE DEFAULT NULL"
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bookings_checked_in_at ON bookings (checked_in_at)"))

    # Check if booking_seats table exists before adding columns
    res_booking_seats = conn.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'booking_seats'")
    ).scalar()
    if res_booking_seats:
        conn.execute(
            text(
                "ALTER TABLE booking_seats ADD COLUMN IF NOT EXISTS checked_in_at TIMESTAMP WITH TIME ZONE DEFAULT NULL"
            )
        )


def init_schema() -> bool:
    """
    Creates tables, enums, and indexes if they do not exist.
    Safe and idempotent via Base.metadata.create_all(checkfirst=True).
    Fast-path: checks if all 11 core tables already exist to eliminate startup DDL latency.
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        _ensure_enum_values_and_columns(conn)

        existing_tables_count = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name IN ("
                "'users', 'events', 'seats', 'holds', 'hold_seats', "
                "'bookings', 'booking_seats', 'audit_logs_0', "
                "'audit_logs_1', 'audit_logs_2', 'audit_logs_3'"
                ")"
            )
        ).scalar()

        if existing_tables_count == 11:
            print("[db_init] All 11 tables verified. Skipping DDL creation.")
            return True

    print("[db_init] Missing tables detected. Running Base.metadata.create_all()...")
    Base.metadata.create_all(bind=engine, checkfirst=True)
    return True


def _get_seed_functions():
    """Dynamically resolves seeding functions regardless of working directory."""
    backend_dir = Path(__file__).resolve().parent.parent.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    try:
        from scripts.seed_users import seed_test_users
        from scripts.seed_demo_data import seed_demo_data
        return seed_test_users, seed_demo_data
    except ImportError:
        from backend.scripts.seed_users import seed_test_users
        from backend.scripts.seed_demo_data import seed_demo_data
        return seed_test_users, seed_demo_data


def seed_users_if_needed() -> bool:
    """
    Ensures seed users exist.
    Skips expensive bcrypt hashing if all configured seed users already exist.
    """
    from app.models.user import User

    required_usernames = [
        settings.SEED_STUDENT_USERNAME,
        settings.SEED_ORGANIZER_USERNAME,
        settings.SEED_ADMIN_USERNAME,
    ]

    with SessionLocal() as db:
        existing_count = db.query(User).filter(User.username.in_(required_usernames)).count()
        if existing_count >= len(required_usernames):
            print("[db_init] All required test users already exist. Skipping user seeding.")
            return True

    print("[db_init] Missing test users detected. Seeding test users...")
    seed_test_users, _ = _get_seed_functions()
    seed_test_users()
    return True


def seed_demo_events_if_needed() -> bool:
    """
    Ensures demo events and sample bookings exist.
    Skips if demo events are already present in the database.
    """
    from app.models.event import Event

    demo_titles = [
        "SeatLock Hackathon Tech Summit 2026",
        "AI Systems & Resilient Database Keynote",
    ]

    with SessionLocal() as db:
        existing_count = db.query(Event).filter(Event.title.in_(demo_titles)).count()
        if existing_count >= len(demo_titles):
            print("[db_init] Demo events already exist. Skipping demo data seeding.")
            return True

    print("[db_init] Demo events missing. Seeding demo events and sample bookings...")
    _, seed_demo_data = _get_seed_functions()
    seed_demo_data()
    return True


def _run_init_steps() -> None:
    """Runs schema creation and conditional seeding."""
    init_schema()
    if settings.AUTO_SEED_DATA:
        seed_users_if_needed()
        seed_demo_events_if_needed()


def init_database_on_startup() -> None:
    """
    Controlled application startup initialization.
    Protected by a PostgreSQL advisory lock to ensure only one worker/process
    performs initialization at a time across instances or restarts.
    """
    print("[db_init] Checking database initialization status...")
    is_postgres = (engine.dialect.name == "postgresql")

    if is_postgres:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            # Acquire PostgreSQL advisory lock (blocks until acquired)
            conn.execute(text(f"SELECT pg_advisory_lock({ADVISORY_LOCK_ID})"))
            try:
                print("[db_init] Acquired PostgreSQL initialization advisory lock.")
                _run_init_steps()
                print("[db_init] Database initialization complete.")
            except Exception as e:
                print(f"[db_init] Error during database initialization: {e}")
                raise
            finally:
                conn.execute(text(f"SELECT pg_advisory_unlock({ADVISORY_LOCK_ID})"))
                print("[db_init] Released PostgreSQL initialization advisory lock.")
    else:
        _run_init_steps()
