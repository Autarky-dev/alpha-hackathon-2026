"""
backend/app/core/database.py
----------------------------
Everything the application needs to talk to PostgreSQL through SQLAlchemy.

Three things are created here:
  1. engine       — the connection pool; one per process.
  2. SessionLocal — a factory that stamps out database sessions.
  3. Base         — the parent class for all ORM table definitions.

A FastAPI dependency (get_db) is also defined here so route handlers can
receive a ready-to-use database session without worrying about cleanup.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


# ---------------------------------------------------------------------------
# 1. Engine
# ---------------------------------------------------------------------------
# The engine is a connection pool — a small cache of open database
# connections that SQLAlchemy manages for you.
#
# create_engine() does NOT open a connection immediately.  The first
# connection is opened when the application first executes a query.
#
# pool_pre_ping=True
#   Before reusing a recycled connection from the pool, SQLAlchemy sends
#   a cheap "SELECT 1" to check whether it is still alive.  This prevents
#   "connection closed" errors after the database server restarts or after
#   long idle periods.
#
# echo=False in production — set to True temporarily when you want to see
# every SQL statement printed to stdout (useful while debugging).
# ---------------------------------------------------------------------------
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=(settings.APP_ENV == "development"),
)


# ---------------------------------------------------------------------------
# 2. Session factory (SessionLocal)
# ---------------------------------------------------------------------------
# sessionmaker() returns a *class* (not an instance).  Every time you call
# SessionLocal() it produces a fresh Session object.
#
# autocommit=False — we control transactions explicitly with
#   session.commit() and session.rollback().
#
# autoflush=False  — SQLAlchemy will not automatically push pending changes
#   to the database before every query.  We flush manually or let commit()
#   do it, which gives us finer control over what hits the database and when.
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# 3. Declarative Base
# ---------------------------------------------------------------------------
# Any SQLAlchemy ORM model (a Python class that maps to a database table)
# must inherit from Base.  SQLAlchemy reads those class definitions and
# knows how to translate them into SQL CREATE TABLE statements and query
# results.
#
# Example (not created yet — this comes in a later phase):
#
#   class Event(Base):
#       __tablename__ = "events"
#       id = mapped_column(Integer, primary_key=True)
#       name = mapped_column(String, nullable=False)
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 4. FastAPI database session dependency
# ---------------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """
    A FastAPI dependency that provides a database session to route handlers.

    Usage in a route:
        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            result = db.execute(text("SELECT 1"))
            ...

    How it works step by step:
      1. FastAPI calls this generator function and receives a Session.
      2. The session is injected into the route handler as the `db` argument.
      3. After the route handler returns (or raises an exception), FastAPI
         resumes this generator — which always reaches the `finally` block.
      4. `finally` guarantees the session is closed even if the handler
         crashed, which returns the underlying connection back to the pool.

    Why a generator?  Python's `yield` splits the function into two parts:
      - Everything before yield runs before the route handler.
      - Everything after yield (the finally block) runs after.
    This is exactly what FastAPI's Depends() machinery expects for cleanup.
    """
    db: Session = SessionLocal()
    try:
        yield db          # hand the session to the route handler
    finally:
        db.close()        # always release the connection back to the pool


# ---------------------------------------------------------------------------
# 5. Startup connection check
# ---------------------------------------------------------------------------
def verify_database_connection(max_retries: int = 5, retry_delay: float = 2.0) -> None:
    """
    Runs a lightweight query to confirm the database is reachable.
    Retries up to max_retries with a delay between attempts to handle
    cloud database warm-up / cold starts.
    """
    import time

    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print("[database] Connection to PostgreSQL verified successfully.")
            return
        except OperationalError:
            if attempt < max_retries:
                print(
                    f"[database] Connection attempt {attempt}/{max_retries} failed. "
                    f"Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                raise RuntimeError(
                    "Could not connect to the database. "
                    "Check DATABASE_URL or DB_* settings in your configuration."
                ) from None
