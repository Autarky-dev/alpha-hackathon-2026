"""
backend/scripts/check_db.py
----------------------------
Standalone connection test script.

Purpose:
  Verify that the application can connect to the PostgreSQL database using
  the credentials in .env, before running the full server.

This script is intentionally simple.  It does exactly three things:
  1. Loads settings (and therefore reads .env).
  2. Opens a real connection to the database.
  3. Runs "SELECT 1" and prints the result.

It does NOT start the FastAPI server.
It does NOT create or modify any tables.
It does NOT use mocked or in-memory databases.

Run from the backend/ directory:
    ../.venv/Scripts/python scripts/check_db.py

Or from the project root:
    .venv/Scripts/python backend/scripts/check_db.py
"""

import sys
# Make sure Python can find the app package (backend/app/...)
# when this script is run directly.
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import engine


def main() -> None:
    print("=" * 55)
    print("  SeatLock — Database Connection Check")
    print("=" * 55)
    print(f"  Host     : {settings.DB_HOST}")
    print(f"  Port     : {settings.DB_PORT}")
    print(f"  Database : {settings.DB_NAME}")
    print(f"  User     : {settings.DB_USER}")
    # Password is intentionally NOT printed.
    print("=" * 55)

    try:
        with engine.connect() as conn:
            # Execute the simplest possible query.
            result = conn.execute(text("SELECT 1 AS connection_ok"))
            row = result.fetchone()

        # Verify we got the expected value back.
        if row and row.connection_ok == 1:
            print("\n  ✓ Connection successful!")
            print("  ✓ PostgreSQL responded correctly to SELECT 1.\n")
            sys.exit(0)
        else:
            print("\n  ✗ Unexpected response from database.\n")
            sys.exit(1)

    except OperationalError as exc:
        # Print the error type but NOT the connection URL (which contains the
        # password).  The raw exc may contain it, so we only print a summary.
        print("\n  ✗ Connection FAILED.")
        print("  Check the following in your .env file:")
        print("    - DB_HOST, DB_PORT  — is the PostgreSQL server running?")
        print("    - DB_NAME           — does the database exist?")
        print("    - DB_USER / DB_PASSWORD — are the credentials correct?")
        print(f"\n  Error type : {type(exc).__name__}")
        sys.exit(1)

    except Exception as exc:
        print(f"\n  ✗ Unexpected error: {type(exc).__name__}: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
