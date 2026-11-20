"""
backend/app/main.py
-------------------
FastAPI application entry point.

Responsibilities:
  - Create the FastAPI app instance.
  - Verify database connectivity at startup.
  - Manage background tasks (periodic hold expiration sweeper) via lifespan context.
  - Register API route handlers.
  - Expose health check endpoint.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.events import router as events_router
from app.core.config import settings
from app.core.database import verify_database_connection
from app.services.hold_cleaner import start_hold_cleaner, stop_hold_cleaner


# ---------------------------------------------------------------------------
# Lifespan — startup and shutdown logic
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    print("[startup] SeatLock API starting up...")
    verify_database_connection()
    # Start periodic background sweeper for expired holds (every 10s)
    start_hold_cleaner(interval_seconds=10)
    yield
    # --- Shutdown ---
    print("[shutdown] Stopping background tasks...")
    await stop_hold_cleaner()
    print("[shutdown] SeatLock API shutting down.")


app = FastAPI(
    title="SeatLock API",
    description="Secure event seat reservation system.",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(events_router, prefix="/events", tags=["Events"])
app.include_router(bookings_router, tags=["Bookings"])
app.include_router(audit_router, prefix="/audit-logs", tags=["Audit Logs"])


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
def health_check():
    """
    Returns 200 OK if the API server is running.
    """
    return {"status": "ok", "service": "SeatLock API"}
