"""
SeatLock — Frontend Preview Server
===================================
A minimal FastAPI app that serves all Jinja2 templates with placeholder
context so the frontend can be visually reviewed without a real database.

Run with:
    uvicorn preview:app --reload --port 8000

Then open http://localhost:8000 in your browser.

This file is for DEVELOPMENT PREVIEW ONLY.
Do NOT use this as the production application entry point.
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="SeatLock — Preview", docs_url=None, redoc_url=None)

# Mount static files
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ---------------------------------------------------------------------------
# Shared context (current_user: None allows api.js to drive real auth session)
# ---------------------------------------------------------------------------

def base_ctx(request: Request, active_page: str = "") -> dict:
    return {
        "request": request,
        "current_user": None,
        "active_page": active_page,
        "flash_messages": [],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request=request, name="events.html", context={
        **base_ctx(request, "events"),
        "events": None,  # let events.js load real events from GET /events
    })


@app.get("/login", response_class=HTMLResponse, name="login")
async def login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={
        "request": request,
        "current_user": None,
        "error": None,
        "field_errors": {},
        "form_values": {},
        "flash_messages": [],
    })


@app.post("/login", response_class=HTMLResponse, name="login_post")
async def login_post(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={
        "request": request,
        "current_user": None,
        "error": None,
        "field_errors": {},
        "form_values": {},
        "flash_messages": [],
    })


@app.get("/events", response_class=HTMLResponse, name="events")
async def events(request: Request):
    return templates.TemplateResponse(request=request, name="events.html", context={
        **base_ctx(request, "events"),
        "events": None,
    })


@app.get("/events/{event_id}/seats", response_class=HTMLResponse, name="seat_map")
async def seat_map(request: Request, event_id: str):
    return templates.TemplateResponse(request=request, name="seat_map.html", context={
        **base_ctx(request, "events"),
        "event": None,
    })


@app.get("/bookings", response_class=HTMLResponse, name="my_bookings")
async def my_bookings(request: Request):
    return templates.TemplateResponse(request=request, name="my_bookings.html", context={
        **base_ctx(request, "my_bookings"),
        "bookings": None,
    })


@app.get("/organizer", response_class=HTMLResponse, name="organizer_dashboard")
async def organizer_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="organizer_dashboard.html", context={
        "request": request,
        "current_user": None,
        "active_page": "organizer",
        "active_section": "overview",
        "flash_messages": [],
    })


@app.get("/admin", response_class=HTMLResponse, name="admin_dashboard")
async def admin_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context={
        "request": request,
        "current_user": None,
        "active_page": "admin",
        "active_section": "overview",
        "flash_messages": [],
    })


@app.get("/logout", response_class=HTMLResponse, name="logout")
async def logout(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login", status_code=302)
