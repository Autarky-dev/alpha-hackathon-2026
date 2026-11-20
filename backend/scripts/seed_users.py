"""
backend/scripts/seed_users.py
-----------------------------
Safe, idempotent user seeding script for SeatLock.

Seeds:
  1. Student user   (role: student)
  2. Organizer user (role: organizer)
  3. Admin user     (role: admin)

Key Design & Security Rules:
  - Credentials are read from environment variables (.env via settings), never hardcoded.
  - Passwords are securely hashed with bcrypt before storing. Plaintext passwords never touch the DB.
  - Safe to rerun: updates existing user hashes/roles without creating duplicate accounts or errors.
  - Never logs or prints passwords, password hashes, or sensitive tokens.
"""

import os
import sys

# Add backend directory to sys.path so app packages can be imported directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.security import hash_password
from app.models.user import User, UserRole


def seed_test_users() -> bool:
    """
    Seed or update test users in the database using configured environment credentials.
    Returns True if seeding succeeds, False otherwise.
    """
    print("=" * 60)
    print("  SeatLock — Test User Seeding (RBAC)")
    print("=" * 60)

    # User definitions derived from settings / environment variables
    users_to_seed = [
        {
            "username": settings.SEED_STUDENT_USERNAME,
            "password": settings.SEED_STUDENT_PASSWORD,
            "role": UserRole.STUDENT,
            "label": "Student",
        },
        {
            "username": settings.SEED_ORGANIZER_USERNAME,
            "password": settings.SEED_ORGANIZER_PASSWORD,
            "role": UserRole.ORGANIZER,
            "label": "Organizer",
        },
        {
            "username": settings.SEED_ADMIN_USERNAME,
            "password": settings.SEED_ADMIN_PASSWORD,
            "role": UserRole.ADMIN,
            "label": "Admin",
        },
    ]

    db: Session = SessionLocal()
    try:
        print(f"  {'Username':<22} | {'Role':<12} | {'Action':<15}")
        print("  " + "-" * 54)

        for item in users_to_seed:
            username = item["username"]
            role = item["role"]
            plain_password = item["password"]

            # Compute bcrypt hash — plaintext password is never stored or logged
            hashed = hash_password(plain_password)

            existing_user = db.query(User).filter(User.username == username).first()

            if existing_user:
                # Idempotent update: update role and password hash without duplicate inserts
                existing_user.role = role
                existing_user.password_hash = hashed
                action = "Updated (synced)"
            else:
                # Create fresh user record
                new_user = User(
                    username=username,
                    password_hash=hashed,
                    role=role,
                )
                db.add(new_user)
                action = "Created (new)"

            print(f"  {username:<22} | {role.value:<12} | {action:<15}")

        db.commit()
        print("=" * 60)
        print("  ✓ All test users seeded successfully.")
        print("=" * 60)
        return True

    except SQLAlchemyError as exc:
        db.rollback()
        print("\n  ✗ Database error while seeding users:")
        print(f"    {type(exc).__name__}: {str(exc)[:150]}")
        return False
    finally:
        db.close()


def main():
    success = seed_test_users()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
